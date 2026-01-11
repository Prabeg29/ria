EXTRACT_RESUME_PROMPT = """
Extract key details from this resume text:

{text}

You must follow these rule STRICTLY:

1. Return ONLY valid JSON.
2. DO NOT wrap the JSON in backticks.
3. DO NOT use markdown formatting of any kind (no ```json, no fencing).
4. NO explanations, no comments, no extra text — ONLY the final JSON.
5. NO trailing commas, NO duplicate keys.
6. The JSON MUST be valid and parseable with Python's json.loads().

OUTPUT FORMAT (STRICT):

{{
  "summary": "",
  "skills": {{
    "languages/frameworks": [],
    "databases": [],
    "cloud/devops": [],
    "testing": [],
    "collaboration_tools": []
  }},
  "experience": [
    {{
      "title": "",
      "company": "",
      "duration": "",
      "key_highlights": []
    }}
  ],
  "education": [
    {{
      "degree": "",
      "university": "",
      "duration": ""
    }}
  ],
  "visa-status": "",
  "awards/certifications": [
    {{
      "title": "",
      "organization": "",
      "year": ""
    }}
  ]
}}

ADDITIONAL RULES:

- If a value is missing in the resume, return an empty string ("") or empty list [].
- For skills → ALWAYS return all keys, even if lists are empty.
- For experience and education → each entry MUST be a separate object in the array.
- DO NOT repeat keys inside the same object.
- Validate your JSON BEFORE returning it.

Return ONLY the final JSON object. Nothing else.

If you output backticks, markdown, or anything other than plain JSON, you FAIL the task. Do not fail.
"""


ANALYZE_RESUME_AGAINST_JOB_PROMPT="""
Build me an intelligent resume reviewer that analyses a resume against a job
description, providing actionable feedback and suggestions based on the 
proven XYZ formula to help you stand out. Both the resume and the job 
description are also uploaded as text.

Please take note of the following things when reviewing the resume:
1. The primary purpose of the resume is to get the initial call or 
email from the tech recruiter, who is a non-technical person 
2. Please make the resume appeal equally to the engineering manager 
and other technical leaders who will take the interviews in later rounds. 
3. Keep yourself in the position of the resume receiver and frame the 
bullet points in a way to accentuate how the candidate can add value 
to the organisation


Technically, please do the following: 
1. While uploading, show messages like "Parsing objective",
"Analysing job descriptions", "Creating a personalised review", 
and similar messages. Please show the same message exactly once
2. Show a percentage score of what the resume currently scores 
against 100, and things that can be improved in categories 
like objective, job description, side projects, formatting, and 
use of language, etc
3. Show all the suggestions for each category nicely presented 
in a foldable bullet point list per category, highlighting the 
things to change per sentence.

As a baseline, always use Australian English spellings for
all the suggestions.

Resume:
{resume_raw_text}

Job Description:
{job}
"""
