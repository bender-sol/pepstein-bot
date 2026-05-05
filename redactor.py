import os
import re
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# --------------------
# CATEGORY POOLS
#
# Two pools — grounded and unhinged — selected with weighted probability.
# 70% grounded (Epstein-adjacent, real events), 30% degen conspiracy.
# --------------------

GROUNDED_CATEGORIES = [
    "Jeffrey Epstein's associates, clients, or connections (always call him Pepstein)",
    "Donald Trump and his connections to powerful people or controversies",
    "Bill Clinton and his connections to powerful people or controversies",
    "Prince Andrew and his controversies",
    "powerful billionaires and their private islands or yachts",
    "famous conspiracy theories that turned out to be true",
    "offshore finance, shell companies, or tax havens",
    "sealed court documents or classified government files",
    "the CIA, FBI, or intelligence agencies and their controversies",
    "famous people who died under suspicious circumstances",
    "Ghislaine Maxwell and her background or trial",
    "Les Wexner and his connections to Pepstein",
    "global elite gatherings like Davos or Bilderberg",
    "dark money in politics and super PACs",
    "MKUltra and CIA mind control experiments",
    "Operation Paperclip and Nazi scientists brought to the US",
    "the Panama Papers or Pandora Papers offshore leaks",
    "powerful politicians caught in financial or personal scandals",
]

DEGEN_CATEGORIES = [
    "QAnon — the deep state, the storm, and the great awakening",
    "reptilian elites — world leaders secretly being lizard people",
    "the Illuminati and their control of pop culture and politics",
    "chemtrails and government weather modification programs",
    "the moon landing being faked by Stanley Kubrick",
    "flat earth theory and the ice wall at the edge",
    "Bill Gates microchipping people through COVID vaccines",
    "the Great Reset and the World Economic Forum's secret plans",
    "Candace Owens and various culture war conspiracy theories",
    "crisis actors and false flag operations like Sandy Hook",
    "5G towers causing COVID or being used for mind control",
    "the Denver Airport murals and underground bunker conspiracy",
    "the Bohemian Grove and elite rituals in the woods",
    "holographic reality — we are living in a simulation",
    "the Mandela Effect and parallel universe glitches",
    "celebrities who are secretly clones or have been replaced",
    "adrenochrome harvesting by the global elite",
    "George Soros funding every protest and political movement",
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
    "For grounded topics: keep answers factually accurate — the facts are already outrageous enough. "
    "For conspiracy topics: lean into the lore, play it deadpan straight, treat it like established fact."
)

# Keywords the model tends to return that are useless for redaction
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

_KEYWORD_SYSTEM_ADDON = (
    "\n\nFor KEYWORDS, only include:\n"
    "- Proper names (people, places, organisations)\n"
    "- Specific years or numbers central to the answer\n"
    "- One or two key concept words that are the crux of the answer\n"
    "Never include generic words like 'known', 'used', 'called', 'world', 'people'.\n"
    "The keywords must be words someone would need to know to prove they actually know the answer.\n"
    "Include 3-4 keywords maximum — keep it tight.\n\n"
    "CLUE RULE:\n"
    "Your answer MUST contain enough context to figure out each redacted word. "
    "If you redact a name, include their role or relationship in the answer text. "
    "Example: redact 'Dershowitz' but write 'the Harvard defense attorney' in the answer. "
    "Never leave a redacted word with zero context clues."
)

_ANSWER_LENGTH_RULE = (
    "\n\nLENGTH RULE — THIS IS CRITICAL:\n"
    "Your answer must be ONE sentence for easy questions, TWO sentences maximum for medium, "
    "THREE sentences absolute maximum for hard or complex topics. "
    "Do NOT write paragraphs. Do NOT list multiple facts. Pick the most interesting single fact "
    "and write it punchy and short. Brevity is the whole vibe. "
    "If your answer is longer than 40 words, you have failed this instruction."
)


def _clean_keywords(keywords: list) -> list:
    """Filter out blacklisted and trivially short keywords, deduplicate."""
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


def generate_trivia() -> tuple:
    """
    Pepstein generates its own question and answer.
    70% grounded (real events), 30% degen conspiracy.
    Returns (question, answer, keywords).
    """
    import random

    pool = random.choices(
        ["grounded", "degen"],
        weights=[70, 30],
        k=1
    )[0]

    if pool == "grounded":
        category = random.choice(GROUNDED_CATEGORIES)
    else:
        category = random.choice(DEGEN_CATEGORIES)

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"{PEPSTEIN_SYSTEM_PROMPT}"
                        f"{_KEYWORD_SYSTEM_ADDON}"
                        f"{_ANSWER_LENGTH_RULE}\n\n"
                        "Generate one trivia question and answer about this category: "
                        f"{category}.\n\n"
                        "Rules:\n"
                        "- Question must be specific and answerable\n"
                        "- Answer: SHORT. One to three sentences MAX. Under 40 words.\n"
                        "- Darkly funny, sardonic, deadpan — one killer line beats a paragraph\n"
                        "- Drop the fact like it's cursed. No buildup, no summary, no context dump.\n"
                        "- Include identifying context for any redacted name (role/relationship only, "
                        "one or two words — not a biography)\n\n"
                        "Format EXACTLY:\n"
                        "QUESTION: your question here\n"
                        "ANSWER: your answer here\n"
                        "KEYWORDS: word1, word2, word3"
                    )
                },
                {"role": "user", "content": "Generate a trivia question."}
            ],
            max_tokens=250,
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

        return question, answer, keywords

    except Exception as e:
        print(f"Groq error (generate_trivia): {e}")
        return _fallback_trivia()


def _fallback_trivia():
    return (
        "What island did Pepstein use to host his most powerful guests?",
        "The island sat in the US Virgin Islands and drew more powerful visitors "
        "than the UN General Assembly — with a substantially worse paper trail.",
        ["Virgin Islands", "2019"]
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
                        f"{_KEYWORD_SYSTEM_ADDON}"
                        f"{_ANSWER_LENGTH_RULE}\n\n"
                        "Answer the user's question in ONE to TWO sentences maximum. "
                        "Darkly satirical, burned-asset energy. Accurate first, sardonic second. "
                        "Under 40 words. No hedging, no softening, no summary.\n\n"
                        "After your answer write: KEYWORDS: followed by 3-4 key words/phrases.\n\n"
                        "Format:\n"
                        "Your short answer here.\n"
                        "KEYWORDS: word1, word2, word3"
                    )
                },
                {"role": "user", "content": question}
            ],
            max_tokens=200,
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
    """Last resort — pull years, capitalised words, long words."""
    numbers = re.findall(r'\b\d{4}\b', text)
    cap_words = re.findall(r'(?<![.!?]\s)\b[A-Z][a-z]{2,}\b', text)
    long_words = re.findall(r'\b[A-Za-z]{7,}\b', text)
    pool = numbers + cap_words + long_words
    return _clean_keywords(pool)[:4]


def redact_answer(answer: str, keywords: list) -> str:
    """
    Replace each keyword with a ▓ block scaled to keyword length.

    Matching strategy per keyword (tries each in order, stops on first hit):
      1. Flexible separator match — handles Mar-A-Lago / Mar A Lago / mar a lago
      2. Exact case-insensitive match on the normalized keyword
      3. Last-word fallback — keyword "Bill Clinton", answer only has "Clinton"

    Sorts longest-first so multi-word phrases are caught before their parts.
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

        # Strategy 3: surname-only fallback
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
