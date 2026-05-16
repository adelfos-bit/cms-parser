from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import anthropic
import fitz  # PyMuPDF
from docx import Document
import tempfile
import os
import json

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

def extract_text_from_pdf(file_bytes: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name
    try:
        doc = fitz.open(tmp_path)
        text = ""
        for page in doc:
            text += page.get_text()
        doc.close()
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
        text = file_bytes.decode("utf-8", errors="ignore")
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
  "name": "성명",
  "phone": "휴대전화번호 (숫자와 하이픈만)",
  "birth_date": "생년월일 (YYYY-MM-DD 형식)",
  "address": "주소",
  "email": "이메일",
  "education": "최종학력",
  "career_1": "주요경력 첫번째",
  "career_2": "주요경력 두번째",
  "position": "직책"
}}

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
    except:
        return {}

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
