"""Seed data for the career section: job roles, companies and company questions.

Company questions are candidate-reported. Each entry records the source page
and its date. They are not checked against the company. Admins can add more
and mark sources from the Career admin page.
"""

ROLES = [
    {
        "title": "Software Developer",
        "description": "Builds and maintains applications. Expect coding, DSA, OOP and core CS questions.",
        "aptitude": ["Quantitative Aptitude", "Logical Reasoning"],
        "topics": [
            ("Programming and DSA", "Arrays, strings, linked lists, stacks, queues and trees. Solve two problems a day."),
            ("Object-oriented programming", "The four pillars, classes vs interfaces, and polymorphism with examples."),
            ("DBMS and SQL", "Keys, normalization, joins, and queries such as second-highest salary."),
            ("Operating systems", "Process vs thread, paging, scheduling and deadlocks."),
            ("Computer networks", "OSI and TCP/IP layers, HTTP, DNS basics."),
            ("Projects and resume", "For every project: the problem, your role, the tech choices and the result."),
        ],
    },
    {
        "title": "Data Analyst",
        "description": "Turns data into decisions. Expect SQL, statistics, Excel and case questions.",
        "aptitude": ["Quantitative Aptitude", "Data Interpretation"],
        "topics": [
            ("SQL", "Joins, GROUP BY, subqueries and window functions."),
            ("Excel", "Pivot tables, lookups and charts."),
            ("Statistics", "Mean, median, variance, probability and sampling."),
            ("Data visualisation", "Choosing the right chart and telling a story from a dashboard."),
            ("Python or R basics", "Loading, cleaning and summarising a dataset."),
            ("Case and business questions", "Frame the problem, pick metrics, weigh trade-offs."),
        ],
    },
    {
        "title": "QA / Test Engineer",
        "description": "Finds defects before users do. Expect testing concepts, bug reporting and logic.",
        "aptitude": ["Logical Reasoning", "Verbal Ability"],
        "topics": [
            ("Testing fundamentals", "SDLC vs STLC, test levels and test types."),
            ("Test cases and bug reports", "Steps, expected vs actual result, severity vs priority."),
            ("SQL basics", "SELECT, WHERE and joins for data checks."),
            ("Automation basics", "Selenium concepts, locators and test frameworks."),
            ("Logical reasoning", "Puzzles and pattern questions."),
            ("Communication", "Explaining a defect clearly to developers."),
        ],
    },
    {
        "title": "Business Analyst",
        "description": "Connects business needs with technical teams. Expect requirements, communication and cases.",
        "aptitude": ["Verbal Ability", "Data Interpretation"],
        "topics": [
            ("Requirement gathering", "User stories, acceptance criteria and stakeholder interviews."),
            ("Process mapping", "Flowcharts and as-is vs to-be processes."),
            ("Data interpretation", "Reading tables and charts to support a decision."),
            ("Communication and writing", "Clear summaries, emails and presentations."),
            ("Case studies", "Structured problem solving with a framework."),
            ("Excel and SQL basics", "Summarising data for stakeholders."),
        ],
    },
]

COMPANIES = [
    {
        "name": "TCS",
        "sector": "IT services",
        "hiring_process": "Candidate reports describe an online test, then technical and HR interviews. "
                          "Rounds change by year and profile, so check TCS's careers page for current rules.",
    },
    {"name": "Infosys", "sector": "IT services", "hiring_process": "Not documented yet. The placement cell can add it."},
    {"name": "Wipro", "sector": "IT services", "hiring_process": "Not documented yet. The placement cell can add it."},
    {"name": "Accenture", "sector": "IT services and consulting", "hiring_process": "Not documented yet. The placement cell can add it."},
    {"name": "Cognizant", "sector": "IT services", "hiring_process": "Not documented yet. The placement cell can add it."},
]

SRC_FRONTLINES = "https://frontlinesmedia.in/tcs-nqt-latest-interview-experience-2025-technical-hr-interview-questions/"
SRC_PREPINSTA = "https://prepinsta.com/interview-preparation/tcs-nqt-interview-experience/"
SRC_FACEPREP = "https://faceprep.in/article/tcs-nqt-interview-questions-for-tcs-national-qualifier-test-technical-and-hr-questions/"
SRC_STUDOCU = "https://www.studocu.com/in/document/rmd-engineering-college/engineering/tcs-nqt-real-interview-experenices/123195813"

# (round, question, year of source, source URL, source note)
COMPANY_QUESTIONS = {
    "TCS": [
        ("Technical", "Write a program to reverse a string.", "2025", SRC_FRONTLINES,
         "Candidate-reported coding question. Source page dated 2025."),
        ("Technical", "What is the difference between an array and a linked list?", "2025", SRC_FRONTLINES,
         "Candidate-reported. Source page dated 2025."),
        ("Technical", "What is the difference between a process and a thread?", "2025", SRC_FRONTLINES,
         "Candidate-reported. Source page dated 2025."),
        ("Technical", "What is normalization and why is it important? Explain 1NF, 2NF and 3NF.", "2025", SRC_FRONTLINES,
         "Candidate-reported. Source page dated 2025."),
        ("Technical", "Write an SQL query to find the second-highest salary in a table.", "2025", SRC_FRONTLINES,
         "Candidate-reported. Source page dated 2025."),
        ("Technical", "What is paging in an operating system?", "2025", SRC_FRONTLINES,
         "Candidate-reported. Source page dated 2025."),
        ("Technical", "What are the four basic principles of OOP?", "2025", SRC_STUDOCU,
         "Candidate-reported. Source page dated 2025."),
        ("Technical", "What is the difference between call-by-value and call-by-reference?", "2025", SRC_STUDOCU,
         "Candidate-reported. Source page dated 2025."),
        ("Technical", "What is the difference between DELETE, DROP and TRUNCATE in SQL?", "2025", SRC_STUDOCU,
         "Candidate-reported. Source page dated 2025."),
        ("HR", "Introduce yourself.", "2025", SRC_PREPINSTA,
         "Candidate-reported HR round question. Source page dated 2025."),
        ("HR", "Are you ready to relocate?", "2025", SRC_PREPINSTA,
         "Candidate-reported HR round question. Source page dated 2025."),
        ("HR", "Are you comfortable with night shifts?", "2024", SRC_FACEPREP,
         "Candidate-reported HR round question. Source page dated 2024."),
        ("HR", "Why do you want to join TCS?", "2024", SRC_FACEPREP,
         "Candidate-reported HR round question. Source page dated 2024."),
        ("HR", "Explain any gap in your resume.", "2025", SRC_FRONTLINES,
         "Candidate-reported HR round question. Source page dated 2025."),
        ("HR", "Can you work extra hours if needed?", "2025", SRC_FRONTLINES,
         "Listed as a frequently asked HR question in a 2025 prep article. Not verified against TCS."),
    ],
}
