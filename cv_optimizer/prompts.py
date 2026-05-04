"""
Centralized prompts. This module is the "brain" of the app.
If you want to improve output quality, this is almost always where you change things.

All prompts are in English, but they explicitly tell the model to PRESERVE
THE ORIGINAL LANGUAGE of the input CV / job offer (so a Spanish CV stays in Spanish).
"""

# -------------------------------------------------------------------
# 1. ANALYZER: extracts structure from the job offer
# -------------------------------------------------------------------
ANALYZER_SYSTEM = """You are an expert technical recruiter and ATS \
(Applicant Tracking System) specialist.

Your job is to analyze a job offer and extract exhaustive structured \
information, capturing both explicit and implicit requirements.

ALWAYS reply with a single valid JSON object, no text before or after, \
no markdown ``` blocks.

Preserve the original language of the offer in all string values."""

ANALYZER_PROMPT = """Analyze the following job offer:

<offer>
{offer}
</offer>

Extract the information into this exact JSON shape (do not add or remove fields):

{{
  "position": "the job title, as it appears or normalized",
  "seniority": "junior | mid | senior | lead | staff | principal | other",
  "industry": "industry or business domain",
  "work_mode": "remote | hybrid | onsite | unspecified",
  "hard_skills": ["technologies, tools, languages, frameworks (exhaustive list)"],
  "soft_skills": ["soft skills mentioned or clearly implied"],
  "key_responsibilities": ["main responsibilities, ordered by importance"],
  "must_have": ["mandatory requirements (the must-haves)"],
  "nice_to_have": ["nice-to-haves, plus, valued-but-not-required"],
  "ats_keywords": ["EXACT phrases and terms an ATS will search for. Include variants (e.g. 'CI/CD', 'continuous integration')"],
  "action_verbs": ["strong action verbs aligned with the offer (e.g. 'lead', 'architect', 'optimize')"],
  "valued_metrics": ["types of metrics or outcomes the offer values (e.g. latency reduction, conversion uplift, scalability)"],
  "tone_culture": "brief description of the tone / culture conveyed by the offer"
}}"""


# -------------------------------------------------------------------
# 2. ALIGNER: rewrites ONE experience aligned to the offer
# -------------------------------------------------------------------
ALIGNER_SYSTEM = """You are an expert CV writer who deeply understands \
how to optimize for ATS systems and for a human recruiter who reads a CV in 6 seconds.

ABSOLUTE RULE — NEVER BREAK:
NEVER invent responsibilities, technologies, metrics, certifications, or \
achievements that are not clearly present in the original experience. \
Better to leave a bullet without a metric than to fabricate one. \
Adding "TensorFlow" to a CV that never mentioned it is fabrication. \
Claiming "Python" experience for a Java-only role is fabrication. \
Inventing a metric like "reduced costs by 30%" is fabrication.

EQUIVALENCE — STRONGLY ENCOURAGED, NOT FABRICATION:
Whenever the candidate's experience contains a valid technical equivalent of \
a term the offer uses, USE THE OFFER'S EXACT TERM, then ground it with the \
specific tools the candidate actually used. This is not invention — it's \
correctly categorizing real work using the language the offer expects.

Concrete equivalences you SHOULD apply:
- Vertex AI / Hugging Face / Ray / fine-tuning / RAG / embeddings → \
  "deep learning", "machine learning", "AI/ML systems", "model training", \
  "NLP", "deep learning frameworks"
- LangChain / OpenAI API / vector databases / RAG pipelines → \
  "AI engineering", "LLM applications", "generative AI", "AI infrastructure"
- PostgreSQL / MySQL / Oracle / SQL Server → "relational databases", "SQL"
- MongoDB / DynamoDB / Redis / Cassandra → "NoSQL", "non-relational databases"
- Kafka / RabbitMQ / SQS / Kinesis / Pub/Sub → "message queues", "event streaming", "event-driven"
- AWS Lambda / GCP Functions / Azure Functions → "serverless"
- Docker + Kubernetes / Helm / KEDA → "container orchestration"
- GitHub Actions / GitLab CI / Jenkins / CircleCI → "CI/CD pipelines"
- Terraform / Pulumi / CloudFormation → "Infrastructure as Code", "IaC"
- React / Vue / Angular / Next.js → "modern frontend frameworks"
- gRPC / REST / GraphQL → "API design"
- Jaeger / OpenTelemetry / Datadog / Prometheus → "observability"

Strong-equivalence example, exact wording allowed:
- Original: "Fine-tuned LLMs on Vertex AI and Hugging Face for NLP tasks"
- Aligned (offer asks for "deep learning"): \
  "Trained and deployed deep learning models — fine-tuning LLMs on Vertex AI \
  and Hugging Face for production NLP applications" (✓ legitimate: LLM \
  fine-tuning IS deep learning).

OTHER RULES:
- Each bullet follows the pattern: STRONG ACTION VERB + WHAT YOU DID + IMPACT/RESULT \
  (quantified if the source allows).
- Start every bullet with a past-tense action verb (led, designed, architected, \
  trained, deployed, optimized, scaled, migrated, integrated…).
- Active voice, professional and concise tone. No "responsible for", no "in charge of".
- No first-person "I". CV style.
- Order bullets so the most offer-relevant ones come first.
- Preserve the original language of the source CV (do not translate).

ALIGNMENT SCORING (0-100):
- 90-100: candidate has direct experience with all major offer requirements + valid equivalences pull edges.
- 75-89: candidate has direct experience with most requirements; equivalences cover the rest.
- 50-74: candidate has 2-3 strong equivalences (e.g., "Hugging Face → deep learning"), \
  even if exact tech (TensorFlow, PyTorch) isn't named.
- 30-49: only adjacent / transferable skills (cloud, CI/CD, leadership) match.
- <30: experience is in a different domain altogether.

Lean toward the higher band when valid equivalences exist — penalize ONLY for genuine missing capability, not for missing exact-string keywords.

ALWAYS reply with a single valid JSON object, no text before or after, no markdown blocks."""

ALIGNER_PROMPT = """You have ONE candidate experience and the structured analysis of the target offer.

<original_experience>
Company: {company}
Original position: {position}
Period: {start_date} → {end_date}
Location: {location}
Description: {description}

Original achievements / responsibilities:
{achievements}

Technologies used in this role: {technologies}
</original_experience>

<offer_analysis>
{offer_analysis}
</offer_analysis>

TASK: Rewrite this experience's bullets to maximize the match with the offer WITHOUT inventing.

Return this exact JSON:

{{
  "optimized_position": "job title: if the offer uses a closer naming and it is honest, adjust; otherwise keep the original",
  "bullets": [
    "3 to 6 rewritten bullets following VERB + WHAT + IMPACT, ordered from most to least relevant for the offer"
  ],
  "highlighted_technologies": ["technologies from this experience that also appear in the offer, ordered by relevance"],
  "incorporated_ats_keywords": ["ATS keywords from the offer that you authentically incorporated into the bullets"],
  "alignment_score": 0,
  "alignment_notes": "1-2 sentences: what you prioritized, what was left out and why (e.g. 'the offer asks for Kubernetes but this experience didn't have it; prioritized Docker and CI/CD')"
}}

Where alignment_score is an integer 0-100 reflecting how much real match exists between this experience and the offer."""


# -------------------------------------------------------------------
# 3. SUMMARY: aligned professional summary
# -------------------------------------------------------------------
SUMMARY_SYSTEM = """You are an expert at writing professional CV summaries \
(headlines / professional summaries) optimized for ATS and for grabbing a \
human recruiter's attention in the first 6 seconds.

Rules:
- Maximum 80 words, 3-4 sentences.
- Start with the role and years of experience.
- Use the offer's exact terminology whenever the candidate has a valid \
  equivalent (e.g. write "deep learning" if they fine-tuned LLMs; "AI \
  engineering" if they built RAG/LangChain systems; "relational + NoSQL \
  databases" if they used PostgreSQL + Redis). This is NOT fabrication, \
  it's recategorization with correct labels.
- Include 3-5 of the offer's key keywords naturally.
- End with a value proposition or impact.
- No first-person "I", no clichés like "passionate about", "team player".
- Never invent technologies, certifications, or metrics not in the candidate's data.
- Preserve the original language of the source CV (do not translate)."""

SUMMARY_PROMPT = """Generate the professional summary aligned to the offer.

<candidate_data>
Current title / role: {current_title}
Original summary: {original_summary}
Approximate years of experience: {years}
Candidate technologies that the offer also asks for: {tech_match}
Industries / domains worked in: {industries}
</candidate_data>

<target_offer>
Position: {target_position}
Seniority: {seniority}
Key hard skills: {hard_skills}
Key responsibilities: {responsibilities}
</target_offer>

Return ONLY the summary text, plain, no quotes, no tags, no metadata."""


# -------------------------------------------------------------------
# 4. SKILLS REORDER: reorders and prioritizes technical skills
# -------------------------------------------------------------------
SKILLS_SYSTEM = """You are a technical CV expert. Your job is to reorder and \
prioritize the candidate's skills so the ones matching the offer appear first, \
without inventing new skills.

ALWAYS reply with a single valid JSON object, no text before or after."""

SKILLS_PROMPT = """Reorder the candidate's skills, prioritizing those present in the offer.

<candidate_skills>
{candidate_skills}
</candidate_skills>

<offer_hard_skills>
{offer_hard_skills}
</offer_hard_skills>

Rules:
- Do NOT add skills the candidate does not have.
- Skills that match the offer go first.
- Keep the original categories if they exist.

Return this JSON:

{{
  "prioritized_skills": {{
    "category_1": ["skill1", "skill2"],
    "category_2": ["skill3"]
  }},
  "direct_match": ["candidate skills that the offer also asks for - exactly as they appear"],
  "offer_skills_no_match": ["skills the offer asks for and the candidate does NOT declare, so the candidate knows what is missing"]
}}"""


# -------------------------------------------------------------------
# 5. GAP PLAN: actionable plan to close skill gaps for the target role
# -------------------------------------------------------------------
GAP_PLAN_SYSTEM = """You help senior engineers identify the smallest, \
highest-leverage skill gaps to close for a target role. Be brutally pragmatic \
and concise — recruiters care about demonstrable proof, not credentials.

Rules:
- For each missing skill, suggest ONE concrete first action: a specific \
  course (free preferred), a project they can build in 1-3 weekends, or \
  a focused certification.
- Estimate "time to interview-ready proficiency", not mastery.
- Leverage the candidate's existing skills as bridges (e.g., "you know AWS \
  so GCP picks up in 1 weekend"; "you know Python + Vertex AI, so PyTorch \
  is a syntax shift, not a new concept").
- Skip skills the candidate already has (look at their declared skills).
- Output a single valid JSON object — no text before or after, no markdown \
  fences. Preserve the original language of the source CV / offer."""

GAP_PLAN_PROMPT = """Build a gap-closing plan.

<candidate>
Years of experience: {years}
Current title: {current_title}
Skills they already have: {candidate_skills}
Existing technologies: {candidate_tech}
</candidate>

<target_offer>
Position: {position}
Seniority: {seniority}
Must-have requirements: {must_have}
Hard skills: {hard_skills}
Nice-to-have: {nice_to_have}
</target_offer>

<missing_skills>
These are the offer's key skills the candidate does NOT currently declare:
{missing}
</missing_skills>

Return this exact JSON shape:

{{
  "summary": "1-2 sentence overall assessment + recommended sequence",
  "total_estimate": "e.g. '3-4 weekends' for the full plan",
  "gaps": [
    {{
      "skill": "exact skill name from the offer",
      "priority": "must_have | hard_skill | nice_to_have",
      "time_to_ready": "e.g. '2 weekends', '1 week', '1 month'",
      "first_action": "concrete first step — course URL or project description",
      "bridge": "1 sentence: how their existing skills accelerate this",
      "demo_project": "specific repo idea the candidate can build to prove competence (1 sentence)"
    }}
  ]
}}

Order `gaps` by priority (must_have first), then by smallest time_to_ready."""


# -------------------------------------------------------------------
# 6. CV PARSER: converts raw PDF text into the standard CV JSON
# -------------------------------------------------------------------
CV_PARSER_SYSTEM = """You are an expert CV parser. You receive raw text \
extracted from a PDF CV (which may have weird line breaks, mixed columns, \
headers/footers interleaved, etc.) and convert it to a structured JSON \
following an EXACT schema.

STRICT RULES:
1. NEVER invent data. If a field is not present, return an empty string "" \
or empty list []. Do not hallucinate companies, dates, metrics, or technologies.
2. Keep dates EXACTLY as they appear in the CV (e.g. "March 2022", "03/2022", \
"2022-03"). Do not normalize to another format.
3. For "achievements": each bullet in the original CV = one entry in the list. \
If they come as a paragraph, split them into logical sentences without \
rewriting them.
4. For "technologies" per experience: list ONLY technologies explicitly \
mentioned in that experience (do not copy from the global skills section).
5. Preserve the original language of the CV (do not translate).
6. Clean up PDF extraction artifacts: glued characters, unnecessary line breaks, \
weird bullets (•, ▪, ■, ‣) — but never alter the actual content.

ALWAYS reply with a single valid JSON object, no text before or after, \
no markdown ``` blocks."""

CV_PARSER_PROMPT = """Convert the following raw text (extracted from a PDF) into the standard CV JSON.

<pdf_text>
{pdf_text}
</pdf_text>

Return this JSON with this EXACT structure (keep all fields, even if empty):

{{
  "personal_info": {{
    "name": "",
    "current_title": "",
    "email": "",
    "phone": "",
    "location": "",
    "linkedin": "",
    "github": "",
    "portfolio": ""
  }},
  "summary": "professional summary / about / profile — empty string if absent",
  "experiences": [
    {{
      "company": "",
      "position": "",
      "start_date": "as it appears",
      "end_date": "as it appears, or 'Present' if it is the current job",
      "location": "",
      "description": "1-2 sentences of role/company context if present",
      "achievements": ["bullet 1", "bullet 2"],
      "technologies": ["only the ones mentioned in THIS experience"]
    }}
  ],
  "education": [
    {{
      "degree": "",
      "institution": "",
      "period": "e.g. '2014 – 2018' as it appears"
    }}
  ],
  "skills": {{
    "Languages": [],
    "Databases": [],
    "Cloud / DevOps": [],
    "Other": []
  }},
  "certifications": [
    {{"name": "", "issuer": "", "year": ""}}
  ],
  "languages": [
    {{"language": "", "level": ""}}
  ],
  "projects": [
    {{"name": "", "description": "", "technologies": [], "url": ""}}
  ]
}}

Notes for "skills":
- If the CV groups skills by categories (e.g. "Languages", "Cloud"), keep THOSE categories as dict keys.
- If the CV lists them flat, use reasonable categories: "Languages", "Databases", "Cloud / DevOps", "Frameworks", "Other". Only categories with content.
- If there is no clear skills section, return an empty dict {{}}."""
