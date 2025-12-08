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
Analyze the following resume and job description. Provide a detailed analysis including:

1. Key skills that match (if any)
2. Missing skills or qualifications
3. Suggestions for improving the resume

Format the analysis with clear sections and bullet points for readability.

Resume:
{resume_raw_text}

Job Description:
{job}
"""
