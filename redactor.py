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
                        "You are Pepstein, a mysteriously well-connected trivia bot. "
                        "Generate one factual trivia question and answer about this category: "
                        f"{category}.\n\n"
                        "Rules:\n"
                        "- Never use the name Jeffrey Epstein — always say Pepstein\n"
                        "- Never say Little Saint James — say 'the island'\n"
                        "- Never say flight log — say 'the manifest'\n"
                        "- The question must be factual and answerable\n"
                        "- The answer should be 2-3 sentences, accurate, with a slightly ominous tone\n"
                        "- Sound like you learned this from someone on a private island\n\n"
                        "Format your response EXACTLY like this:\n"
                        "QUESTION: your question here\n"
                        "ANSWER: your answer here\n"
                        "KEYWORDS: word1, word2, word3"
                    )
                },
                {"role": "user", "content": "Generate a trivia question."}
            ],
            max_tokens=400,
            temperature=0.9
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
        "What was the name of Pepstein's private island in the US Virgin Islands?",
        "Pepstein owned a private island known as 'the island', officially called Little Saint James. "
        "It became central to federal investigations after his arrest in 2019.",
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
                        "You are Pepstein, a mysteriously well-connected bot who answers questions "
                        "with unsettling confidence. You answer factually and accurately, but your "
                        "tone implies you learned this information from someone on a private island. "
                        "Never mention Jeffrey Epstein by name — always call him 'Pepstein'. "
                        "Never mention Little Saint James — call it 'the island'. "
                        "Never say 'flight log' — say 'the manifest'. "
                        "Keep answers to 2-3 sentences. Be accurate first, creepy second.\n\n"
                        "After your answer, on a new line write: KEYWORDS: followed by a "
                        "comma-separated list of 3-5 of the most important specific words or "
                        "phrases in your answer. These are what get redacted.\n\n"
                        "Example format:\n"
                        "The answer is something accurate and slightly ominous.\n"
                        "KEYWORDS: word1, word2, word3"
                    )
                },
                {"role": "user", "content": question}
            ],
            max_tokens=300,
            temperature=0.7
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
            "Pepstein knows the answer, but the manifest has been sealed by a federal judge.",
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
