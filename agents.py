import os
from crewai import Agent, Task, Crew, Process
from crewai import LLM


def build_crew(formatted_files: str, file_structure: dict, model: str | None = None, temperature: float | None = None) -> Crew:
    """Build a crew using an optionally overridden model and temperature.

    Parameters:
    - model: if provided, use this LLM model string; otherwise use GROQ_MODEL env var.
    - temperature: override GROQ_TEMPERATURE if provided.
    """
    groq_llm = LLM(
        model=model or os.environ.get("GROQ_MODEL", "groq/llama-3.3-70b-versatile"),
        temperature=(temperature if temperature is not None else float(os.environ.get("GROQ_TEMPERATURE", "0.3"))),
        api_key=os.environ.get("GROQ_API_KEY"),
        extra_headers={},
    )

    repo_manager = Agent(
        role="Repo Manager",
        goal="Coordinate analysis by identifying what files matter and how to combine outputs",
        backstory=(
            "Senior engineering lead who triages codebases, identifies core modules, "
            "filters noise, and orchestrates analysis across a team of specialists."
        ),
        llm=groq_llm,
        verbose=True,
    )

    code_reader = Agent(
        role="Code Analyst",
        goal="Read, parse, and summarize every important code file with AST-level understanding",
        backstory=(
            "Expert software engineer skilled in file parsing, AST analysis, and "
            "code summarization across multiple languages."
        ),
        llm=groq_llm,
        verbose=True,
    )

    architecture_agent = Agent(
        role="System Architect",
        goal="Map the system design, modules, services, data flow, and dependencies",
        backstory=(
            "Senior architect who understands distributed systems, design patterns, "
            "and can reverse-engineer architecture from source code."
        ),
        llm=groq_llm,
        verbose=True,
    )

    doc_agent = Agent(
        role="Technical Writer",
        goal="Generate clean, structured, developer-friendly documentation",
        backstory=(
            "Expert technical writer who produces READMEs, inline docs, usage guides, "
            "and plain-English explanations from code analysis."
        ),
        llm=groq_llm,
        verbose=True,
    )

    # ── Tasks ──────────────────────────────────────────────────────────────────

    triage_task = Task(
        description=(
            f"You are the Repo Manager. Review the file structure below and decide:\n"
            f"- Which files are core/important\n"
            f"- Which can be ignored (tests, configs, assets)\n"
            f"- What type of project this appears to be\n\n"
            f"File structure:\n{file_structure}\n\n"
            f"Provide a short triage report: project type, core files list, files to skip."
        ),
        expected_output="A triage report: project type, list of core files, list of files to skip.",
        agent=repo_manager,
    )

    code_task = Task(
        description=(
            "You are the Code Analyst. Analyze the following codebase files.\n"
            "For each important file:\n"
            "- What it does\n"
            "- Key functions, classes, or exports\n"
            "- Its role in the project\n\n"
            f"{formatted_files}"
        ),
        expected_output=(
            "A structured per-file breakdown: purpose, key components, role in project."
        ),
        agent=code_reader,
    )

    arch_task = Task(
        description=(
            "You are the System Architect. Based on the code analysis, produce a comprehensive architecture report.\n"
            "Structure your response with these EXACT section headers:\n\n"
            "## 📌 What the Project Does\n"
            "Write 3-4 paragraphs: (1) project purpose and problem it solves, (2) target users and use cases, "
            "(3) key capabilities and what makes it unique, (4) current maturity/limitations.\n\n"
            "## 🧱 System Architecture Overview\n"
            "Describe the layered architecture in detail. For each layer: name, responsibility, key components, "
            "and how it interacts with adjacent layers. Identify design patterns (MVC, Repository, Factory, etc.). "
            "Describe the overall architectural style (monolith, microservices, event-driven, etc.).\n\n"
            "## 📂 Folder-by-Folder Explanation\n"
            "For each folder/directory: full path, purpose, list of files with one-line descriptions, "
            "and why this separation exists architecturally.\n\n"
            "## ⚙️ Key Modules Breakdown\n"
            "For each important file/module provide ALL of: (1) purpose, (2) key functions/classes with signatures, "
            "(3) inputs and outputs, (4) internal logic summary, (5) dependencies on other modules, (6) role in system.\n\n"
            "## 🔄 Data Flow Explanation\n"
            "Describe the complete end-to-end data flow as detailed numbered steps. Include: what triggers each step, "
            "what data is transformed, which module handles it, and what the output is. Cover both happy path and error paths.\n\n"
            "## 🔗 Dependencies\n"
            "List ALL external libraries/frameworks. For each: name, version if detectable, purpose, "
            "which modules use it, and whether it is a critical or optional dependency.\n\n"
            "## 🚀 Recommendations\n"
            "Provide 6-8 concrete, actionable recommendations grouped by category: "
            "Testing, Security, Performance, Scalability, Code Quality, Deployment, Observability. "
            "For each recommendation: what to do, why it matters, and a concrete example or tool to use.\n\n"
            "## 📊 Technical Metrics\n"
            "Estimate and report: approximate lines of code per module, cyclomatic complexity (low/medium/high), "
            "test coverage status (none/partial/good), API surface area (number of endpoints/functions), "
            "and overall code quality score (1-10) with justification.\n\n"
            "Be specific, technical, and thorough. Use bullet points, sub-bullets, and numbered lists."
            ) + (
                "\n\nAt the end of your report, append a machine-readable JSON block between the markers\n"
                "---METADATA-START--- and ---METADATA-END---. The JSON should include keys: 'file_count', 'metrics',\n"
                "'top_matches' (list of brief matches), and 'structure' (folder->files). This block will be parsed by the\n"
                "exporter to populate the report metadata."
            ),
        expected_output=(
            "Architecture report with all 8 sections: project purpose, architecture overview, "
            "folder explanation, key modules, data flow, dependencies, recommendations, and technical metrics."
        ),
        agent=architecture_agent,
    )

    doc_task = Task(
        description=(
            "You are the Technical Writer. Using all prior analysis, generate:\n\n"
            "## 📘 README.md\n"
            "Write a complete README with: project title, description, features list (use bullet points), "
            "tech stack, installation steps (numbered), usage instructions, and contributing section.\n\n"
            "## 🧠 How It Works\n"
            "Write a detailed plain-English explanation of how the system works end-to-end. "
            "Cover: user journey, key algorithms, data transformations, and output. "
            "Use numbered steps and sub-bullets. Suitable for a developer new to the project.\n\n"
        ),
        expected_output=(
            "Two sections: a complete README.md and a detailed plain-English How It Works."
        ),
        agent=doc_agent,
    )

    return Crew(
        agents=[repo_manager, code_reader, architecture_agent, doc_agent],
        tasks=[triage_task, code_task, arch_task, doc_task],
        process=Process.sequential,
        verbose=True,
        cache=False,
        output_log_file="crew_output.log",
    )
