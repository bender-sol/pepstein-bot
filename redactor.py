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

def generate_trivia() -> tuple[str, str, list[str]]:
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
                        f"{PEPSTEIN_SYSTEM_PROMPT}\n\n"
                        "Generate one factual trivia question and answer about this category: "
                        f"{category}.\n\n"
                        "Rules:\n"
                        "- The question must be factual and specific\n"
                        "- The answer should be 2-3 sentences, accurate, darkly funny, and slightly unhinged\n"
                        "- Write like someone who knows where the bodies are and is annoyed nobody else does\n"
                        "- Do not editorialize with phrases like 'it's worth noting' — just drop the facts like they're cursed\n\n"
                        "Format your response EXACTLY like this:\n"
                        "QUESTION: your question here\n"
                        "ANSWER: your answer here\n"
                        "KEYWORDS: word1, word2, word3"
                    )
                },
                {"role": "user", "content": "Generate a trivia question."}
            ],
            max_tokens=400,
            temperature=0.95
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

        answer = re.sub(r'jeffrey epstein', 'Pepstein', answer, flags=re.IGNORECASE)
        answer = re.sub(r'\bepstein\b', 'Pepstein', answer, flags=re.IGNORECASE)
        question = re.sub(r'jeffrey epstein', 'Pepstein', question, flags=re.IGNORECASE)
        question = re.sub(r'\bepstein\b', 'Pepstein', question, flags=re.IGNORECASE)

        if not question or not answer:
            return _fallback_trivia()

        return question, answer, keywords

    except Exception as e:
        print(f"Groq error: {e}")
        return _fallback_trivia()


def _fallback_trivia():
    return (
        "What was the official name of Pepstein's private island in the US Virgin Islands?",
        "Little Saint James — or as Pepstein called it, 'the island' — sat in the US Virgin Islands "
        "and somehow attracted more powerful visitors than the UN General Assembly, "
        "but with a substantially worse paper trail. Federal investigators arrested him in 2019, "
        "by which point half of Washington had apparently lost their calendars.",
        ["Little Saint James", "US Virgin Islands", "2019"]
    )


def get_answer(question: str) -> tuple[str, list[str]]:
    """Answer a user-supplied question with Pepstein flavoring."""
    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"{PEPSTEIN_SYSTEM_PROMPT}\n\n"
                        "Answer the user's question factually and accurately in 2-3 sentences. "
                        "Your tone should be darkly satirical — like a burned intelligence asset "
                        "reading from a dossier they weren't supposed to keep. "
                        "Be accurate first, outrageously sardonic second. "
                        "Do not hedge or soften. The facts are already doing the work.\n\n"
                        "After your answer, on a new line write: KEYWORDS: followed by a "
                        "comma-separated list of 3-5 of the most important specific words or "
                        "phrases in your answer. These are what get redacted.\n\n"
                        "Example format:\n"
                        "The answer is something accurate and deeply cursed.\n"
                        "KEYWORDS: word1, word2, word3"
                    )
                },
                {"role": "user", "content": question}
            ],
            max_tokens=300,
            temperature=0.85
        )
        full_text = response.choices[0].message.content.strip()

        if "KEYWORDS:" in full_text:
            parts = full_text.split("KEYWORDS:")
            answer = parts[0].strip()
            keywords_raw = parts[1].strip()
            keywords = [k.strip() for k in keywords_raw.split(",") if k.strip()]
        else:
            answer = full_text
            keywords = extract_keywords_simple(full_text)

        answer = re.sub(r'jeffrey epstein', 'Pepstein', answer, flags=re.IGNORECASE)
        answer = re.sub(r'\bepstein\b', 'Pepstein', answer, flags=re.IGNORECASE)

        return answer, keywords

    except Exception as e:
        print(f"Groq error: {e}")
        return (
            "Pepstein knows the answer, but the manifest has been sealed by a federal judge "
            "who is coincidentally also on the manifest.",
            ["manifest", "federal judge"]
        )


def extract_keywords_simple(text: str) -> list[str]:
    words = re.findall(r'\b[A-Za-z]{6,}\b', text)
    return list(set(words))[:5]


def redact_answer(answer: str, keywords: list[str]) -> str:
    redacted = answer
    for keyword in keywords:
        escaped = re.escape(keyword)
        redacted = re.sub(escaped, "[REDACTED]", redacted, flags=re.IGNORECASE)
    return redacted


def check_guess(guess: str, keywords: list[str]) -> list[str]:
    guess_lower = guess.lower().strip()
    matched = []
    for keyword in keywords:
        if keyword.lower() in guess_lower or guess_lower in keyword.lower():
            matched.append(keyword)
    return matched
