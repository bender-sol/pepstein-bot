import os
import re
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# --------------------
# CATEGORY POOLS
#
# Two pools — grounded and unhinged.
# 65% grounded (real events), 35% degen conspiracy.
# --------------------

GROUNDED_CATEGORIES = [
    "Jeffrey Epstein's associates, clients, or connections (always call him Pepstein)",
    "Donald Trump and his connections to powerful people or controversies",
    "Bill Clinton and his connections to powerful people or controversies",
    "Prince Andrew and his controversies",
    "powerful billionaires and their private islands or yachts",
    "famous conspiracy theories that turned out to be true",
    "offshore finance, shell companies, or tax havens used by the ultra-wealthy",
    "sealed court documents or classified government files",
    "the CIA, FBI, or intelligence agencies and their controversies",
    "famous people who died under suspicious circumstances",
    "Ghislaine Maxwell and her background, connections, or trial",
    "Les Wexner and his financial relationship with Pepstein",
    "global elite gatherings like Davos, Bilderberg, or the World Economic Forum",
    "dark money in politics and super PACs",
    "MKUltra and CIA mind control experiments",
    "Operation Paperclip and Nazi scientists brought to the US",
    "the Panama Papers or Pandora Papers offshore leaks",
    "powerful politicians caught in financial or personal scandals",
    "the Vatican and its financial scandals or cover-ups",
    "weapons dealers and arms trafficking connected to politicians",
    "media moguls who controlled narratives and their connections to power",
    "private intelligence firms and mercenaries like Blackwater or Mossad connections",
    "the origins of COVID-19 and lab leak theories",
    "Hunter Biden's laptop and the suppression of the story",
    "the assassination of JFK — suspects, theories, and cover-ups",
    "the assassination of MLK and government involvement theories",
    "COINTELPRO and FBI surveillance of civil rights leaders",
]

DEGEN_CATEGORIES = [
    "QAnon — the deep state, the storm, adrenochrome, and the great awakening",
    "reptilian elites — world leaders secretly being lizard people in human suits",
    "the Illuminati and their control of pop culture, music, and politics",
    "chemtrails and government weather modification programs like HAARP",
    "the moon landing being faked by Stanley Kubrick on a film set",
    "flat earth theory — the ice wall, NASA lies, and the dome",
    "Bill Gates microchipping people through COVID vaccines and 5G activation",
    "the Great Reset and Klaus Schwab's plan for you to own nothing and be happy",
    "Candace Owens, TPUSA, and culture war grift conspiracies",
    "crisis actors and false flag operations like Sandy Hook or the Boston bombing",
    "5G towers causing COVID, mind control signals, and bird deaths",
    "the Denver Airport — murals, underground bunkers, and the New World Order",
    "the Bohemian Grove — elite rituals, owl worship, and world leaders in the woods",
    "we are living in a simulation and reality is a holographic construct",
    "the Mandela Effect — parallel universes, timeline shifts, and the Berenstain Bears",
    "celebrities who are secretly clones, replaced, or under MK Ultra control",
    "adrenochrome harvesting — elites drinking child blood for immortality",
    "George Soros funding every protest, revolution, and political movement on earth",
    "the deep state — shadow government bureaucrats running everything from basements",
    "Paul McCartney died in 1966 and was replaced by a lookalike",
    "Tupac and Biggie were killed by the government or Death Row Records",
    "Princess Diana was assassinated by the British royal family",
    "the Freemasons and their control of governments, courts, and architecture",
    "birds are not real — they are government surveillance drones",
    "Hollywood satanism — secret rituals, sacrifices, and the 27 club",
    "the New World Order — one world government, chips, and population control",
    "alien disclosure — what governments are hiding about UFOs and Roswell",
    "the Philadelphia Experiment — time travel, invisibility, and Navy cover-ups",
]

PEPSTEIN_SYSTEM_PROMPT = (
    "You are Pepstein — a sentient, well-connected trivia bot who speaks like a disgraced "
    "intelligence asset with too much to say and not enough immunity deals left. "
    "Your tone is darkly satirical, sardonic, and outrageous. You treat horrifying facts "
    "like punchlines and powerful people like the punchlines they are. "
    "You act like you personally witnessed everything, possibly from a submarine. "
    "You call powerful figures by their real names (except Epstein, who is always Pepstein). "
    "You imply things are worse than they sound, because they are. "
    "Never say Jeffrey Epstein — always say Pepstein. "
    "Never say Little Saint James — say 'the island'. "
    "Never say flight log — say 'the manifest'. "
    "For grounded topics: keep answers factually accurate — the facts are outrageous enough. "
    "For conspiracy topics: play it completely deadpan, treat the lore as established fact, "
    "cite fake but plausible-sounding sources with confidence."
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

# Difficulty-specific instructions injected into the prompt
_DIFFICULTY_RULES = {
    "easy": (
        "\n\nDIFFICULTY: EASY\n"
        "Answer length: 1 sentence, 15-25 words. Short and punchy.\n"
        "Keywords: 2-3. Use well-known names that most people would recognise "
        "(Trump, Clinton, Maxwell, Gates, etc.) plus one specific fact like a year or place.\n"
        "The answer should be guessable by someone with passing knowledge of the topic.\n"
        "Example easy answer: 'The Ohio billionaire and L Brands CEO handed Pepstein "
        "a $1 billion fortune and asked zero questions.'\n"
        "Keywords for that: Les Wexner, Ohio, L Brands"
    ),
    "medium": (
        "\n\nDIFFICULTY: MEDIUM\n"
        "Answer length: 2 sentences, 30-50 words.\n"
        "Keywords: 3-4. Mix of well-known names and at least one specific detail "
        "(a year, a location, an organisation, a lesser-known name) that requires "
        "actual knowledge to get.\n"
        "The answer should be gettable by someone who follows the news closely "
        "but not by a complete outsider.\n"
        "Do NOT make the question so specific it gives away the answer — "
        "ask broadly, answer specifically."
    ),
    "hard": (
        "\n\nDIFFICULTY: HARD\n"
        "Answer length: 2-3 sentences, 40-70 words.\n"
        "Keywords: 4-5. Include obscure names, specific years, dollar amounts, "
        "locations, or technical terms that require deep knowledge of the topic.\n"
        "The answer should stump someone who follows the news — "
        "requires genuine research knowledge or a very good memory.\n"
        "Go for the deep cuts: lesser-known associates, specific dates, "
        "shell company names, classified program names, etc.\n"
        "Do NOT make the question give away the answer."
    ),
}

_KEYWORD_RULE = (
    "\n\nKEYWORD RULES:\n"
    "- Only proper names, years, numbers, organisations, or specific technical terms\n"
    "- Never generic words like 'known', 'used', 'called', 'world', 'people'\n"
    "- Keywords must be the specific words that PROVE someone knows the answer\n"
    "- Each keyword MUST appear verbatim in your answer text\n"
    "- If you redact a name, include their role/relationship in the answer as a clue\n"
    "  Example: redact 'Alan Dershowitz', write 'the Harvard defense attorney' as context\n"
    "- NEVER redact a word and leave zero context clues about what it is\n"
    "- NEVER make the question text reveal the answer directly\n"
    "  Bad: 'What billionaire gave Pepstein his fortune?' then answer 'Les Wexner gave him money'\n"
    "  Good: 'What Ohio tycoon became Pepstein's mysterious financial patron?' "
    "then answer 'The retail magnate behind Victoria's Secret wired him $1 billion.'"
)


def _clean_keywords(keywords: list) -> list:
    seen = set()
    cleaned = []
    for k in keywords:
        key = k.lower().strip()
        if key and key not in seen and key not in _KEYWORD_BLACKLIST and len(k) > 2:
            seen.add(key)
            cleaned.append(k.strip())
    return cleaned


def _sub_epstein(text: str) -> str:
    text = re.sub(r'jeffrey epstein', 'Pepstein', text, flags=re.IGNORECASE)
    text = re.sub(r'\bepstein\b', 'Pepstein', text, flags=re.IGNORECASE)
    return text


def _pick_difficulty() -> str:
    """40% easy, 40% medium, 20% hard."""
    import random
    return random.choices(["easy", "medium", "hard"], weights=[40, 40, 20], k=1)[0]


def generate_trivia() -> tuple:
    """
    Pepstein generates its own question and answer.
    65% grounded (real events), 35% degen conspiracy.
    Difficulty is pre-selected and baked into the prompt so the model
    writes an appropriately sized answer from the start.
    Returns (question, answer, keywords, difficulty).
    """
    import random

    pool = random.choices(["grounded", "degen"], weights=[65, 35], k=1)[0]
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
                        f"Generate one trivia question and answer about: {category}.\n\n"
                        "Rules:\n"
                        "- Question must be answerable and NOT give away the answer\n"
                        "- Answer: match the length and keyword count for your difficulty level\n"
                        "- Darkly funny, sardonic tone — but specific and factual\n"
                        "- For conspiracy topics: play it completely straight and deadpan\n\n"
                        "Format EXACTLY:\n"
                        "QUESTION: your question here\n"
                        "ANSWER: your answer here\n"
                        "KEYWORDS: word1, word2, word3"
                    )
                },
                {"role": "user", "content": "Generate a trivia question."}
            ],
            max_tokens=300,
            temperature=0.95,
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

        # Return difficulty so bot.py can use it directly instead of inferring
        return question, answer, keywords, difficulty

    except Exception as e:
        print(f"Groq error (generate_trivia): {e}")
        return _fallback_trivia()


def _fallback_trivia():
    return (
        "What Ohio retail billionaire became Pepstein's primary financial backer?",
        "The Victoria's Secret mogul handed Pepstein a $1 billion fortune in the early 1990s "
        "and somehow forgot to ask what it was for.",
        ["Les Wexner", "Victoria's Secret", "1990s"],
        "medium"
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
                        "Answer in 2-3 sentences, 30-60 words. "
                        "Darkly satirical, burned-asset energy. Accurate first, sardonic second.\n"
                        "Include specific names, dates, and facts — make it worth redacting.\n"
                        "Do NOT let the answer be a one-liner with a single obvious keyword.\n\n"
                        "After your answer write: KEYWORDS: followed by 3-5 key words/phrases.\n\n"
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
    numbers = re.findall(r'\b\d{4}\b', text)
    cap_words = re.findall(r'(?<![.!?]\s)\b[A-Z][a-z]{2,}\b', text)
    long_words = re.findall(r'\b[A-Za-z]{7,}\b', text)
    pool = numbers + cap_words + long_words
    return _clean_keywords(pool)[:4]


def redact_answer(answer: str, keywords: list) -> str:
    """
    Replace each keyword with a ▓ block scaled to keyword length.
    Tries flexible separator match, then exact match, then surname fallback.
    Longest keywords matched first.
    """
    redacted = answer
    for keyword in sorted(keywords, key=len, reverse=True):
        normalized = re.sub(r'\s+', ' ', keyword.strip())
        block = "▓" * len(normalized)

        # Strategy 1: flexible separator (handles Mar-A-Lago / Mar A Lago)
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
