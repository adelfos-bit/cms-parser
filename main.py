import os
import json
import tempfile
import subprocess
import anthropic
from fastapi import FastAPI, UploadFile, File, HTTPException
from docx import Document
import fitz

app = FastAPI()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

def extract_text_from_pdf(file_bytes: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name
    try:
        doc = fitz.open(tmp_path)
        text = "\n".join([page.get_text() for page in doc])
        return text
    finally:
        os.unlink(tmp_path)

def extract_text_from_docx(file_bytes: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name
    try:
        doc = Document(tmp_path)
        text = "\n".join([para.text for para in doc.paragraphs])
        return text
    finally:
        os.unlink(tmp_path)

def extract_text_from_hwp(file_bytes: bytes) -> str:
    try:
        text = file_bytes.decode("utf-16-le", errors="ignore")
        # 의미있는 한글/영문/숫자만 추출
        import re
        # 꺾쇠 안의 내용 추출
        chunks = re.findall(r"<([^<>]{1,50})>", text)
        meaningful = []
        for chunk in chunks:
            chunk = chunk.strip().replace(" ", "")
            if chunk and len(chunk) > 1:
                meaningful.append(chunk)
        if meaningful:
            return "\n".join(meaningful)
        # fallback
        cleaned = "".join(c for c in text if c.isprintable() or c in "\n\t ")
        return cleaned
    except:
        return ""

def parse_with_claude(text: str) -> dict:
    if not ANTHROPIC_API_KEY:
        return {}
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    prompt = f"""다음은 이력서 텍스트입니다. 아래 정보를 추출해서 JSON으로만 응답해주세요.
다른 설명 없이 JSON만 반환하세요.

{{
  "name": "성명 (한글 이름)",
  "phone": "휴대전화번호 (숫자와 하이픈만)",
  "birth_date": "생년월일 (YYYY-MM-DD 형식)",
  "address": "주소",
  "email": "이메일",
  "education": "최종학력",
  "career_1": "주요경력 첫번째",
  "career_2": "주요경력 두번째",
  "position": "직책"
}}

찾을 수 없는 항목은 빈 문자열로 반환하세요.
참고: 텍스트에 "<이 호 종>" 처럼 꺾쇠괄호와 공백이 포함될 수 있으니 공백을 무시하고 읽어주세요.
예: "<이 호 종>" -> "이호종", "<010-7219-1959>" -> "010-7219-1959"

이력서 텍스트:
{text[:3000]}"""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}]
    )

    response_text = message.content[0].text.strip()

    try:
        if "```" in response_text:
            response_text = response_text.split("```")[1]
            if response_text.startswith("json"):
                response_text = response_text[4:]
        return json.loads(response_text)
    except Exception as ex:
        return {"_debug": response_text[:200], "_error": str(ex)}


@app.get("/test-claude")
def test_claude():
    if not ANTHROPIC_API_KEY:
        return {"error": "API key not set", "key_length": 0}
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=50,
            messages=[{"role": "user", "content": "say hi in JSON: {"hi": true}"}]
        )
        return {"success": True, "response": msg.content[0].text, "key_length": len(ANTHROPIC_API_KEY)}
    except Exception as e:
        return {"error": str(e), "key_length": len(ANTHROPIC_API_KEY)}

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/parse")
async def parse_file(file: UploadFile = File(...)):
    try:
        file_bytes = await file.read()
        filename = file.filename.lower()

        if filename.endswith(".pdf"):
            text = extract_text_from_pdf(file_bytes)
        elif filename.endswith(".docx"):
            text = extract_text_from_docx(file_bytes)
        elif filename.endswith(".hwp"):
            text = extract_text_from_hwp(file_bytes)
        else:
            raise HTTPException(status_code=400, detail="지원하지 않는 파일 형식")

        if not text.strip():
            return {"success": False, "message": "텍스트 추출 실패", "data": {}}

        parsed = parse_with_claude(text)

        return {
            "success": True,
            "data": parsed,
            "raw_text": text[:500]
        }
    except Exception as e:
        return {"success": False, "message": str(e), "data": {}}
