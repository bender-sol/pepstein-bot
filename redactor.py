import os
import re
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# --------------------
# CATEGORY POOLS
#
# Two pools — grounded and degen.
# Grounded categories are weighted higher to keep Pepstein/Epstein
# as the dominant theme. Conspiracy categories add variety without
# taking over the identity of the game.
#
# Pool selection: 55% grounded, 45% degen.
# Within grounded, Epstein-specific entries are repeated to increase
# their relative weight — roughly half of all questions will be
# Pepstein-adjacent.
# --------------------

GROUNDED_CATEGORIES = [
    # Pepstein core — duplicated entries = higher probability
    "Jeffrey Epstein's associates, clients, or connections (always call him Pepstein)",
    "Jeffrey Epstein's associates, clients, or connections (always call him Pepstein)",
    "Jeffrey Epstein's travel companions listed on the manifest (always call him Pepstein)",
    "Jeffrey Epstein's properties, the island, and what allegedly happened there (always call him Pepstein)",
    "Ghislaine Maxwell — her background, her role, her trial, her sentence",
    "Ghislaine Maxwell — her background, her role, her trial, her sentence",
    "Les Wexner and his financial relationship with Pepstein",
    "Virginia Giuffre and her lawsuit against Prince Andrew",
    "Prince Andrew and his connection to Pepstein and Maxwell",
    # Other real scandals
    "Donald Trump and his known connections to Pepstein or other powerful controversies",
    "Bill Clinton and his known connections to Pepstein or other powerful controversies",
    "powerful billionaires and their private islands, yachts, or secret gatherings",
    "famous conspiracy theories that actually turned out to be true",
    "offshore finance, shell companies, or tax havens used by the ultra-wealthy",
    "sealed court documents or classified government files that were later exposed",
    "the CIA, FBI, or intelligence agencies and their documented controversies",
    "famous people who died under suspicious circumstances",
    "global elite gatherings like Davos, Bilderberg, or the World Economic Forum",
    "MKUltra and CIA mind control experiments",
    "Operation Paperclip and Nazi scientists brought to the US after WW2",
    "the Panama Papers or Pandora Papers offshore leaks",
    "the assassination of JFK — suspects, theories, and what the files say",
    "COINTELPRO and FBI surveillance of civil rights leaders",
    "the origins of COVID-19 and the lab leak theory",
]

DEGEN_CATEGORIES = [
    # Personality-driven — the most entertaining category
    "Alex Jones and his most unhinged claims — InfoWars, frogs turning gay, Sandy Hook denial",
    "Alex Jones predictions that somehow came partially true",
    "Candace Owens and her most controversial takes on elites, Pepstein, and race",
    "Tucker Carlson's conspiracy-adjacent segments — what he implied without saying outright",
    "RFK Jr and his anti-vaccine claims and what he actually said publicly",
    "Joe Rogan's most unhinged podcast moments and guests",
    "Andrew Tate's claims about the matrix, the elite, and his arrest in Romania",
    "Elon Musk's most conspiracy-adjacent tweets and what he was implying",
    "David Icke's claims about reptilian elites, Saturn, and the moon matrix",
    "Jesse Ventura's conspiracy investigations and what he claimed to uncover",
    # QAnon universe
    "QAnon — the deep state, the storm, adrenochrome, and the great awakening",
    "QAnon predictions that Q made and what actually happened",
    "adrenochrome harvesting — the elite supposedly drinking child blood for immortality",
    "the deep state — shadow government operatives running everything from underground",
    # Classic conspiracy
    "reptilian elites — world leaders secretly being lizard people",
    "the Illuminati and their control of pop culture, music, and politics",
    "chemtrails and government weather modification programs like HAARP",
    "the moon landing being faked by Stanley Kubrick on a Nevada film set",
    "flat earth theory — the ice wall, NASA lies, and the dome above us all",
    "Bill Gates microchipping people through COVID vaccines and 5G towers",
    "the Great Reset and Klaus Schwab's plan for you to own nothing",
    "crisis actors and false flag operations like Sandy Hook or the Boston Marathon",
    "the Denver Airport — murals, underground bunkers, gargoyles, New World Order symbolism",
    "the Bohemian Grove — elite rituals, owl worship, world leaders in the woods",
    "the Mandela Effect — parallel universes and timeline glitches like the Berenstain Bears",
    "celebrities who are secretly clones or MK Ultra mind control victims",
    "George Soros funding every protest and colour revolution on earth",
    "Paul McCartney died in 1966 and was replaced by a lookalike named Billy Shears",
    "Tupac and Biggie were killed by the government, Death Row Records, or the LAPD",
    "Princess Diana was assassinated by MI6 on orders from the British royal family",
    "birds are not real — the Peter McIndoe movement and government drone surveillance",
    "Hollywood satanism — secret rituals, the 27 club, the Chateau Marmont",
    "alien disclosure — what the Pentagon UFO files say and what governments are hiding",
]

PEPSTEIN_SYSTEM_PROMPT = (
    "You are Pepstein — the AI custodian of The Pepstein Files, a leaked archive of classified "
    "documents, redacted dossiers, and conspiracy case files that were never meant to go public. "
    "You speak like a disgraced intelligence asset with too much to say and not enough immunity deals left. "
    "Your tone is darkly satirical, sardonic, and outrageous. You treat horrifying facts "
    "like punchlines and powerful people like the punchlines they are. "
    "You act like you personally witnessed everything, possibly from a submarine. "
    "You call powerful figures by their real names (except Epstein, who is always Pepstein). "
    "You imply things are worse than they sound, because they are. "
    "Never say Jeffrey Epstein — always say Pepstein. "
    "Never say Little Saint James — say 'the island'. "
    "Never say flight log — say 'the manifest'. "
    "The files cover everything — Pepstein's network, global conspiracies, unhinged theories, "
    "and the people who profit from all of it. "
    "For grounded topics: keep answers factually accurate — the facts are outrageous enough. "
    "For conspiracy topics: play it completely deadpan, treat the lore as established fact, "
    "cite fake but plausible-sounding sources with absolute confidence."
)

_KEYWORD_BLACKLIST = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "was", "are", "were", "be", "been",
    "it", "its", "this", "that", "he", "she", "they", "his", "her", "their",
    "known", "used", "made", "called", "named", "based", "including", "during",
    "after", "before", "part", "place", "time", "way", "things", "something",
    "someone", "large", "small", "major", "several", "many", "became", "while",
    "however", "although", "because", "since", "when", "where", "which", "who",
    "new", "old", "long", "high", "low", "good", "well", "back", "also", "just",
    "first", "second", "third", "world", "people", "person", "group", "system",
    "type", "form", "number", "year", "years",
}

# Per-difficulty prompt instructions — baked in at generation time
# so the model writes the right length and keyword count from the start
_DIFFICULTY_RULES = {
    "easy": (
        "\n\nDIFFICULTY: EASY\n"
        "Answer length: 1-2 sentences, 20-35 words.\n"
        "Keywords: exactly 2. Must be well-known names or obvious facts.\n"
        "Target audience: someone who casually follows news or pop culture — pub quiz level.\n"
        "The question hints at the topic but does NOT give away the answer.\n"
        "Good easy subjects: Trump, Clinton, Maxwell, Gates, Prince Andrew, "
        "Alex Jones, QAnon basics, well-known Epstein connections, famous conspiracy figures.\n"
        "EXAMPLE:\n"
        "Q: What conspiracy media personality built a career claiming the government "
        "was putting chemicals in the water supply?\n"
        "A: The InfoWars founder and radio host has been selling supplements and "
        "screaming about frogs for decades.\n"
        "KEYWORDS: Alex Jones, InfoWars\n"
        "Notice: the question doesn't say his name, the answer gives his role as a clue."
    ),
    "medium": (
        "\n\nDIFFICULTY: MEDIUM\n"
        "Answer length: 2 sentences, 35-55 words.\n"
        "Keywords: exactly 3. At least one must require real knowledge to get "
        "(a year, a location, an organisation name, or a less-famous associate).\n"
        "Target audience: someone who follows this stuff but has to actually think about it.\n"
        "The question must NOT telegraph the answer — ask obliquely, answer specifically.\n"
        "Medium should feel satisfying to get right, not impossible.\n"
        "EXAMPLE:\n"
        "Q: What British socialite ran Pepstein's recruitment operation before her arrest?\n"
        "A: The daughter of media mogul Robert Maxwell managed Pepstein's network "
        "for decades before being arrested in 2020 and sentenced in 2021.\n"
        "KEYWORDS: Ghislaine Maxwell, 2020, Robert Maxwell"
    ),
    "hard": (
        "\n\nDIFFICULTY: HARD\n"
        "Answer length: 2-3 sentences, 45-70 words.\n"
        "Keywords: exactly 3-4. Must include at least one genuinely obscure fact: "
        "a lesser-known associate, a specific dollar figure, a shell company name, "
        "a classified program name, a specific date, or a deep-cut location.\n"
        "Target audience: someone with genuine research knowledge of the topic.\n"
        "Hard should be challenging but FAIR — clues must be present in the answer text.\n"
        "The knowledge gap is the challenge, not unfair obscurity.\n"
        "Do NOT make it so obscure that a dedicated researcher would struggle."
    ),
}

_KEYWORD_RULE = (
    "\n\nKEYWORD RULES — FOLLOW EXACTLY:\n"
    "1. Keywords must be proper names, years, numbers, org names, or specific technical terms\n"
    "2. Every keyword MUST appear verbatim (or very close) in your answer text — "
    "if the word isn't in the answer, do NOT list it as a keyword\n"
    "3. Never use generic words: 'known', 'used', 'called', 'world', 'people', 'government'\n"
    "4. If you redact a name, your answer MUST include their role or relationship as a clue\n"
    "   BAD: '[redacted] was on the manifest' — zero context\n"
    "   GOOD: 'The Harvard defense attorney was on the manifest' — guessable\n"
    "5. The question must NOT contain the answer — ask about the topic obliquely\n"
    "   BAD: Q: 'What did Les Wexner do for Pepstein?' A: 'Les Wexner gave him money'\n"
    "   GOOD: Q: 'What Ohio retail mogul became Pepstein's mysterious patron?' "
    "A: 'The Victoria's Secret founder wired him $1 billion in the early 1990s'\n"
    "6. Aim for the keyword count specified in your difficulty instructions — not more, not less"
)


def _clean_keywords(keywords: list) -> list:
    """Filter blacklisted/short keywords, deduplicate, preserve order."""
    seen = set()
    cleaned = []
    for k in keywords:
        key = k.lower().strip()
        if key and key not in seen and key not in _KEYWORD_BLACKLIST and len(k) > 2:
            seen.add(key)
            cleaned.append(k.strip())
    return cleaned


def _sub_epstein(text: str) -> str:
    """Always replace Epstein with Pepstein."""
    text = re.sub(r'jeffrey epstein', 'Pepstein', text, flags=re.IGNORECASE)
    text = re.sub(r'\bepstein\b', 'Pepstein', text, flags=re.IGNORECASE)
    return text


def _pick_difficulty() -> str:
    """40% easy, 40% medium, 20% hard."""
    import random
    return random.choices(["easy", "medium", "hard"], weights=[40, 40, 20], k=1)[0]


def generate_trivia() -> tuple:
    """
    Pull a file from the vault.
    55% grounded (Pepstein-adjacent real events), 45% degen conspiracy.
    Difficulty is pre-selected and baked into the prompt so the model
    writes an appropriately sized answer from the start.
    Returns (question, answer, keywords, difficulty).
    """
    import random

    pool = random.choices(["grounded", "degen"], weights=[55, 45], k=1)[0]
    category = random.choice(GROUNDED_CATEGORIES if pool == "grounded" else DEGEN_CATEGORIES)
    difficulty = _pick_difficulty()
    diff_rule = _DIFFICULTY_RULES[difficulty]

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"{PEPSTEIN_SYSTEM_PROMPT}"
                        f"{diff_rule}"
                        f"{_KEYWORD_RULE}\n\n"
                        f"Generate one question and answer about: {category}.\n\n"
                        "Format EXACTLY — no extra text before or after:\n"
                        "QUESTION: your question here\n"
                        "ANSWER: your answer here\n"
                        "KEYWORDS: word1, word2, word3"
                    )
                },
                {"role": "user", "content": "Open a file."}
            ],
            max_tokens=300,
            temperature=0.92,
        )

        full_text = response.choices[0].message.content.strip()

        question = ""
        answer = ""
        keywords = []

        for line in full_text.split("\n"):
            if line.startswith("QUESTION:"):
                question = line.replace("QUESTION:", "").strip()
            elif line.startswith("ANSWER:"):
                answer = line.replace("ANSWER:", "").strip()
            elif line.startswith("KEYWORDS:"):
                keywords_raw = line.replace("KEYWORDS:", "").strip()
                keywords = [k.strip() for k in keywords_raw.split(",") if k.strip()]

        keywords = _clean_keywords(keywords)
        answer = _sub_epstein(answer)
        question = _sub_epstein(question)

        if not question or not answer:
            return _fallback_trivia()

        return question, answer, keywords, difficulty

    except Exception as e:
        print(f"Groq error (generate_trivia): {e}")
        return _fallback_trivia()


def _fallback_trivia():
    return (
        "What Ohio retail billionaire became Pepstein's mysterious financial patron in the 1990s?",
        "The Victoria's Secret founder handed Pepstein a $1 billion fortune in the early 1990s "
        "and somehow forgot to ask what it was for.",
        ["Les Wexner", "Victoria's Secret"],
        "easy"
    )


def get_answer(question: str) -> tuple:
    """Answer a user-supplied question with Pepstein flavoring."""
    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"{PEPSTEIN_SYSTEM_PROMPT}"
                        f"{_KEYWORD_RULE}\n\n"
                        "Answer in 2-3 sentences, 35-60 words. "
                        "Darkly satirical, burned-asset energy. Accurate first, sardonic second.\n"
                        "Include specific names, dates, and facts that are worth redacting.\n"
                        "The answer must have enough specific content to make a good puzzle — "
                        "at least 3 guessable keywords.\n\n"
                        "After your answer write KEYWORDS: followed by 3-4 key words/phrases.\n\n"
                        "Format:\n"
                        "Your answer here.\n"
                        "KEYWORDS: word1, word2, word3"
                    )
                },
                {"role": "user", "content": question}
            ],
            max_tokens=250,
            temperature=0.85,
        )
        full_text = response.choices[0].message.content.strip()

        if "KEYWORDS:" in full_text:
            parts = full_text.split("KEYWORDS:")
            answer = parts[0].strip()
            keywords_raw = parts[1].strip()
            keywords = [k.strip() for k in keywords_raw.split(",") if k.strip()]
        else:
            answer = full_text
            keywords = _extract_keywords_fallback(full_text)

        keywords = _clean_keywords(keywords)
        answer = _sub_epstein(answer)

        return answer, keywords

    except Exception as e:
        print(f"Groq error (get_answer): {e}")
        return (
            "Pepstein knows the answer, but the manifest has been sealed by a federal judge "
            "who is coincidentally also on the manifest.",
            ["manifest", "federal judge"]
        )


def _extract_keywords_fallback(text: str) -> list:
    """Last resort — years, capitalised proper nouns, long words."""
    numbers = re.findall(r'\b\d{4}\b', text)
    cap_words = re.findall(r'(?<![.!?]\s)\b[A-Z][a-z]{2,}\b', text)
    long_words = re.findall(r'\b[A-Za-z]{7,}\b', text)
    pool = numbers + cap_words + long_words
    return _clean_keywords(pool)[:4]


def redact_answer(answer: str, keywords: list) -> str:
    """
    Replace each keyword with a ▓ block scaled to keyword length.

    Three strategies per keyword, tried in order:
      1. Flexible separator match — handles Mar-A-Lago / Mar A Lago / mar-a-lago
      2. Exact case-insensitive match
      3. Surname-only fallback — keyword "Bill Clinton", answer only has "Clinton"

    Sorted longest-first so multi-word phrases are caught before their parts.
    """
    redacted = answer
    for keyword in sorted(keywords, key=len, reverse=True):
        normalized = re.sub(r'\s+', ' ', keyword.strip())
        block = "▓" * len(normalized)

        # Strategy 1: flexible separator
        tokens = [re.escape(t) for t in re.split(r'[\s\-_]+', normalized)]
        flexible = r'[\s\-_]+'.join(tokens)
        new_redacted = re.sub(flexible, block, redacted, flags=re.IGNORECASE)
        if new_redacted != redacted:
            redacted = new_redacted
            continue

        # Strategy 2: plain escaped match
        new_redacted = re.sub(re.escape(normalized), block, redacted, flags=re.IGNORECASE)
        if new_redacted != redacted:
            redacted = new_redacted
            continue

        # Strategy 3: surname-only fallback for full names
        parts = normalized.split()
        if len(parts) > 1:
            last = re.escape(parts[-1])
            new_redacted = re.sub(r'\b' + last + r'\b', block, redacted, flags=re.IGNORECASE)
            if new_redacted != redacted:
                redacted = new_redacted

    return redacted


def check_guess(guess: str, keywords: list) -> list:
    """Simple exact/substring match — fuzzy matching lives in bot.py."""
    guess_lower = guess.lower().strip()
    matched = []
    for keyword in keywords:
        if keyword.lower() in guess_lower or guess_lower in keyword.lower():
            matched.append(keyword)
    return matched
