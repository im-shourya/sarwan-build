# Used when the live roadmap call fails or is too slow during a demo.
ROADMAP = {
    "weeks": [
        {
            "weekNumber": 1,
            "focus": "Foundations: arrays, hashing, processes",
            "topics": [
                {"name": "Arrays & Two Pointers", "category": "DSA", "why": "Most common first-round pattern."},
                {"name": "Hash Maps & Sets", "category": "DSA", "why": "Turns O(n^2) lookups into O(n)."},
                {"name": "Processes vs Threads", "category": "OS", "why": "Frequent OS warm-up question."},
            ],
            "dailyChallenges": ["Two Sum", "Container With Most Water", "Explain context switching"],
        },
        {
            "weekNumber": 2,
            "focus": "Linked structures and memory",
            "topics": [
                {"name": "Linked Lists", "category": "DSA", "why": "Tests pointer manipulation under pressure."},
                {"name": "Stacks & Queues", "category": "DSA", "why": "Base for monotonic stack and BFS problems."},
                {"name": "Virtual Memory & Paging", "category": "OS", "why": "Classic OS depth question."},
            ],
            "dailyChallenges": ["Reverse a Linked List", "Valid Parentheses", "Explain a page fault"],
        },
        {
            "weekNumber": 3,
            "focus": "Trees, graphs, and concurrency",
            "topics": [
                {"name": "Binary Trees & BST", "category": "DSA", "why": "Recursion fluency is heavily tested."},
                {"name": "Graphs: BFS/DFS", "category": "DSA", "why": "Appears in most product-company loops."},
                {"name": "Deadlocks & Synchronization", "category": "OS", "why": "Shows systems maturity."},
            ],
            "dailyChallenges": ["Level Order Traversal", "Number of Islands", "Dining philosophers"],
        },
        {
            "weekNumber": 4,
            "focus": "DP and system design basics",
            "topics": [
                {"name": "Dynamic Programming", "category": "DSA", "why": "Separates strong candidates."},
                {"name": "Designing a URL Shortener", "category": "System Design", "why": "Canonical entry-level design."},
                {"name": "Caching & Load Balancing", "category": "System Design", "why": "Building blocks of every design round."},
            ],
            "dailyChallenges": ["Climbing Stairs", "Longest Increasing Subsequence", "Design a rate limiter"],
        },
    ]
}
