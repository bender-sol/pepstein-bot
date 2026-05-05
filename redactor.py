import os
import re
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

TRIVIA_CATEGORIES = [
    "Jeffrey Epstein's associates, clients, or connections (always call him Pepstein)",
    "Donald Trump and his connections to powerful people or controversies",
    "Bill Clinton and his connections to powerful people or controversies",
    "Prince Andrew and his controversies",
    "powerful billionaires and their private islands or yachts",
    "famous conspiracy theories that turned out to be true",
    "offshore finance, shell companies, or tax havens",
    "private Caribbean islands and their owners",
    "sealed court documents or classified government files",
    "the CIA, FBI, or intelligence agencies and their controversies",
    "famous people who died in suspicious circumstances",
    "Ghislaine Maxwell and her background or trial",
    "Les Wexner and his connections",
    "global elite gatherings like Davos or Bilderberg",
    "dark money in politics",
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
    "You keep answers factually accurate — the facts are already outrageous enough."
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

# Injected into every system prompt to get better keywords from the model
_KEYWORD_SYSTEM_ADDON = (
    "\n\nFor KEYWORDS, only include:\n"
    "- Proper names (people, places, organisations)\n"
    "- Specific years or numbers central to the answer\n"
    "- Technical terms or titles that are the crux of the answer\n"
    "Never include generic words like 'known', 'used', 'called', 'world', 'people'.\n"
    "The keywords must be the specific words someone would need to know to prove "
    "they actually know the answer — not just words that appear in it.\n"
    "Include at least 4 keywords.\n\n"
    "CRITICAL — CLUE RULE:\n"
    "Your answer MUST contain enough context that a reader can figure out what "
    "the redacted words are. If you redact a name, the answer must include their "
    "role, nationality, relationship, or some other identifying detail. "
    "Example: if 'Alan Dershowitz' is redacted, write 'the celebrity defense attorney' "
    "or 'Harvard law professor' in the answer so players have something to work with. "
    "Never redact a name and leave zero context about who that person is."
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
    Pepstein generates its own question and answer from Epstein-adjacent topics.
    Returns (question, answer, keywords).
    """
    import random
    category = random.choice(TRIVIA_CATEGORIES)

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"{PEPSTEIN_SYSTEM_PROMPT}"
                        f"{_KEYWORD_SYSTEM_ADDON}\n\n"
                        "Generate one factual trivia question and answer about this category: "
                        f"{category}.\n\n"
                        "Rules:\n"
                        "- The question must be factual and specific\n"
                        "- The answer should be 2-3 sentences, accurate, darkly funny, "
                        "and slightly unhinged\n"
                        "- Write like someone who knows where the bodies are and is annoyed "
                        "nobody else does\n"
                        "- Do not editorialize with phrases like 'it's worth noting' — "
                        "just drop the facts like they're cursed\n"
                        "- The answer MUST contain identifying context for every name you "
                        "include as a keyword (role, title, relationship, nationality, etc.) "
                        "so players can figure out who is being redacted\n\n"
                        "Format your response EXACTLY like this:\n"
                        "QUESTION: your question here\n"
                        "ANSWER: your answer here\n"
                        "KEYWORDS: word1, word2, word3, word4"
                    )
                },
                {"role": "user", "content": "Generate a trivia question."}
            ],
            max_tokens=450,
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
        "What was the official name of Pepstein's private island in the US Virgin Islands?",
        "Little Saint James — or as Pepstein called it, 'the island' — sat in the US Virgin "
        "Islands and somehow attracted more powerful visitors than the UN General Assembly, "
        "but with a substantially worse paper trail. Federal investigators arrested him in 2019, "
        "by which point half of Washington had apparently lost their calendars.",
        ["Little Saint James", "US Virgin Islands", "2019", "Washington"]
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
                        f"{_KEYWORD_SYSTEM_ADDON}\n\n"
                        "Answer the user's question factually and accurately in 2-3 sentences. "
                        "Your tone should be darkly satirical — like a burned intelligence asset "
                        "reading from a dossier they weren't supposed to keep. "
                        "Be accurate first, outrageously sardonic second. "
                        "Do not hedge or soften. The facts are already doing the work.\n\n"
                        "The answer MUST contain identifying context for every name you include "
                        "as a keyword — role, title, relationship, or some other clue — so players "
                        "can figure out who is being redacted.\n\n"
                        "After your answer, on a new line write: KEYWORDS: followed by a "
                        "comma-separated list of 4-5 of the most important specific words or "
                        "phrases — names, dates, places, numbers only.\n\n"
                        "Example format:\n"
                        "The answer is something accurate and deeply cursed.\n"
                        "KEYWORDS: word1, word2, word3, word4"
                    )
                },
                {"role": "user", "content": question}
            ],
            max_tokens=350,
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
    """
    Last resort keyword extraction when the model doesn't return a KEYWORDS line.
    Prioritises capitalised words and years over random long words.
    """
    numbers = re.findall(r'\b\d{4}\b', text)
    cap_words = re.findall(r'(?<![.!?]\s)\b[A-Z][a-z]{2,}\b', text)
    long_words = re.findall(r'\b[A-Za-z]{7,}\b', text)

    pool = numbers + cap_words + long_words
    return _clean_keywords(pool)[:5]


def redact_answer(answer: str, keywords: list) -> str:
    """
    Replace each keyword with a ▓ block the same length as the word.
    Multi-word keywords get a single solid block across the full phrase.
    Handles hyphenated variants (Mar-A-Lago / Mar A Lago) by normalizing separators.
    Sorts longest-first so "Bill Clinton" is caught before "Clinton".
    """
    redacted = answer
    for keyword in sorted(keywords, key=len, reverse=True):
        normalized = re.sub(r'\s+', ' ', keyword.strip())
        block = "▓" * len(normalized)

        # Build pattern that matches the keyword with any separator style
        # e.g. "Mar-A-Lago" matches "Mar A Lago", "mar-a-lago", "Mar A-Lago" etc.
        tokens = re.split(r'[\s\-_]+', re.escape(normalized))
        flexible = r'[\s\-_]+'.join(tokens)

        redacted = re.sub(flexible, block, redacted, flags=re.IGNORECASE)
    return redacted


def check_guess(guess: str, keywords: list) -> list:
    """Simple exact/substring match — fuzzy matching lives in bot.py."""
    guess_lower = guess.lower().strip()
    matched = []
    for keyword in keywords:
        if keyword.lower() in guess_lower or guess_lower in keyword.lower():
            matched.append(keyword)
    return matched
