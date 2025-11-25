import re
import unicodedata


class TextPreprocessor:
    def __init__(self, text: str = ""):
        if not text or not text.strip():
            raise ValueError("Input text cannot be empty or whitespace only.")

        self.text = text

    def remove_extra_whitespace(self):
        self.text = re.sub(r"\s+", " ", self.text).strip()
        return self

    def normalize_unicode(self):
        self.text = self.text.lower()
        self.text = re.sub(r"[•▪●◦∙‣⁃]", "-", self.text)
        self.text = unicodedata.normalize("NFKC", self.text)
        return self

    def remove_boilerplates(self):
        boilerplate_patterns = [
            r"^\s*curriculum vitae\.?\s*$",
            r"^\s*resume\.?\s*$",
            r"^\s*curriculum vitae -?$",
            r"^\s*page\s*\d+(\s*of\s*\d+)?\s*$",
            r"^\s*\d+\s*$",
        ]

        for pat in boilerplate_patterns:
            self.text = re.sub(pat, "", self.text, flags=re.IGNORECASE)

        return self

    def redact_pii(self):
        self.text = re.sub(r"\S+@\S+", "[REDACTED_EMAIL]", self.text)

        linkedin_patterns = [
            # full URLs e.g. https://www.linkedin.com/in/username or linkedin.com/in/username?...
            r"\b(?:https?://)?(?:www\.)?linkedin\.com[^\s,;]*",
            # textual mentions like "linkedin: username" or "linkedin - username"
            r"\blinkedin\s*[:\-]\s*\S+",
        ]

        for pat in linkedin_patterns:
            self.text = re.sub(
                pat, "[REDACTED_LINKEDIN]", self.text, flags=re.IGNORECASE
            )

        github_patterns = [
            r"\b(?:https?://)?(?:www\.)?github\.com[^\s,;]*",
            r"\bgithub\s*[:\-]\s*\S+",
        ]

        for pat in github_patterns:
            self.text = re.sub(pat, "[REDACTED_GITHUB]", self.text, flags=re.IGNORECASE)

        phone_patterns = [
            # international +61 / 0061, optional (0) and flexible separators
            r"(?:(?:\+|00)61)[\s\-\.\(]*(?:0\)?[\s\-\.\)]*)?(?:\d{1,4}[\s\-\.\)]?\d{3}[\s\-\.\)]?\d{3,4})",
            # Australian mobile e.g., 0412 345 678 or 0412345678
            r"\b04[\s\-\.\)]*\d{2}[\s\-\.\)]*\d{3}[\s\-\.\)]*\d{3}\b",
        ]

        for pat in phone_patterns:
            self.text = re.sub(pat, "[REDACTED_PHONE]", self.text, flags=re.IGNORECASE)

        return self

    def chunk_text(self):
        pass

    def get_text(self):
        return self.text
