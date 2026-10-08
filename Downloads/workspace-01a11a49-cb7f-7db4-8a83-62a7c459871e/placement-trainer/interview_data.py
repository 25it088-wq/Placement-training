"""Interview question bank.

Each tuple: (interview type, question, expected concepts)

Expected concepts are readable words. The scorer matches them by stem, so
"decided" also matches "decision", and "motivation" matches "motivated".
Multi-word concepts such as "primary key" must appear as written.
"""

TYPES = ["HR", "Behavioural", "Technical"]

INTERVIEW_QUESTIONS = [
    # ---- HR ----
    ("HR", "Tell me about yourself.",
     ["education", "skills", "project", "experience", "goals", "interests"]),
    ("HR", "Why do you want to work for this company?",
     ["company", "values", "growth", "learn", "role", "contribute"]),
    ("HR", "Where do you see yourself in five years?",
     ["grow", "skills", "lead", "role", "learn", "contribute"]),
    ("HR", "What are your greatest strengths?",
     ["strengths", "example", "skills", "team", "results"]),
    ("HR", "What is your biggest weakness and what are you doing about it?",
     ["weakness", "improve", "working on", "aware", "steps"]),
    ("HR", "Why should we hire you?",
     ["skills", "experience", "value", "contribute", "fit"]),
    ("HR", "What motivates you?",
     ["motivation", "goals", "learning", "impact", "challenge"]),
    ("HR", "Are you comfortable with relocation or flexible working hours?",
     ["yes", "flexible", "willing", "commit", "shift"]),

    # ---- Behavioural (answer with STAR) ----
    ("Behavioural", "Describe a time you faced a difficult challenge in a team.",
     ["team", "challenge", "resolved", "result", "learned"]),
    ("Behavioural", "Tell me about a time you failed. What did you do?",
     ["failed", "mistake", "learned", "fixed", "next time"]),
    ("Behavioural", "Give an example of when you had to meet a tight deadline.",
     ["deadline", "prioritize", "plan", "delivered", "time"]),
    ("Behavioural", "Describe a situation where you disagreed with a teammate.",
     ["disagreed", "listen", "compromise", "outcome", "respect"]),
    ("Behavioural", "Tell me about a time you showed leadership.",
     ["lead", "team", "decided", "motivate", "result"]),
    ("Behavioural", "Describe a project you are proud of.",
     ["project", "built", "role", "impact", "learned"]),
    ("Behavioural", "Tell me about a time you learned a new skill quickly.",
     ["learned", "quickly", "practice", "applied", "result"]),
    ("Behavioural", "Describe a time you helped a classmate or colleague.",
     ["helped", "support", "explain", "outcome", "result"]),

    # ---- Technical (CS fundamentals) ----
    ("Technical", "What is the difference between a process and a thread?",
     ["process", "thread", "memory", "shares", "lightweight", "context"]),
    ("Technical", "Explain what a primary key is in a database.",
     ["primary key", "unique", "null", "identifies", "row"]),
    ("Technical", "What is the difference between SQL and NoSQL databases?",
     ["relational", "schema", "table", "document", "scalable"]),
    ("Technical", "What is Big O notation?",
     ["complexity", "time", "input", "grow", "worst"]),
    ("Technical", "What happens when you type a URL into a browser?",
     ["DNS", "TCP", "HTTP", "server", "response", "render"]),
    ("Technical", "Explain the four pillars of object-oriented programming.",
     ["encapsulation", "inheritance", "polymorphism", "abstraction"]),
    ("Technical", "What is a hash table and when would you use one?",
     ["key", "hash", "collision", "lookup", "average"]),
    ("Technical", "What is version control and why use Git?",
     ["history", "branch", "commit", "collaboration", "revert"]),
]
