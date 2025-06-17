from flask import Flask, render_template, request, redirect, session, send_file
from werkzeug.security import generate_password_hash, check_password_hash
from fpdf import FPDF
import fitz  # PyMuPDF
import os, json, tempfile, uuid, re
import requests
import mysql.connector
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")
UPLOAD_FOLDER = 'uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
TOGETHER_API_KEY = os.getenv("TOGETHER_API_KEY")

# Database connections
def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv("MYSQL_HOST"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.getenv("MYSQL_USER"),
        password=os.getenv("MYSQL_PASSWORD"),
        database=os.getenv("MYSQL_DB"),
        ssl_ca=os.getenv("MYSQL_SSL_CA")
    )

# Extract text from uploaded PDF
def extract_text(pdf_path):
    doc = fitz.open(pdf_path)
    return " ".join([page.get_text() for page in doc]).strip()

# Together API question generator
def generate_questions(prompt):
    headers = {
        "Authorization": f"Bearer {TOGETHER_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "meta-llama/Llama-3-70b-chat-hf",
        "max_tokens": 1500,
        "temperature": 0.7,
        "top_p": 0.7,
        "messages": [{"role": "user", "content": prompt}]
    }
    res = requests.post("https://api.together.xyz/v1/chat/completions", headers=headers, json=data)
    if res.status_code == 200:
        return res.json()['choices'][0]['message']['content']
    return ""

# Sanitize quotes & code blocks
def sanitize_ai_response(text):
    text = text.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    text = re.sub(r"```json|```", "", text)
    return text.strip()

@app.route('/')
def home():
    if 'user_id' not in session:
        return redirect('/login')
    return render_template('index.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = generate_password_hash(request.form['password'])
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("INSERT INTO users (username, email, password) VALUES (%s, %s, %s)",
                        (username, email, password))
            conn.commit()
            cur.close()
            conn.close()
            return redirect('/login')
        except Exception as e:
            return f"\u274c Signup Failed: {str(e)}"
    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT id, password FROM users WHERE email=%s", (email,))
            user = cur.fetchone()
            cur.close()
            conn.close()

            if user and check_password_hash(user[1], password):
                session['user_id'] = user[0]
                return redirect('/')
            return "Invalid credentials"
        except Exception as e:
            return f"\u274c Login Failed: {str(e)}"
    return render_template('login.html')

@app.route('/generate_exam', methods=['POST'])
def generate_exam():
    if 'user_id' not in session:
        return redirect('/login')

    file = request.files['pdf']
    exam_type = request.form['exam_type']
    filename = str(uuid.uuid4()) + ".pdf"
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)
    text = extract_text(filepath)

    if exam_type == 'mcq':
        num = int(request.form.get('num_questions', 0) or 0)
        if num <= 0:
            return "Please enter a valid number of MCQs."

        prompt = f"""
You are a test-set generator. Based on the study material below, return exactly {num} multiple-choice questions.

\u26a0\ufe0f Return ONLY valid JSON. No explanations.

Format:
[
  {{
    "question": "What is Python?",
    "options": ["A. Snake", "B. Language", "C. Car", "D. Movie"],
    "answer": "B. Language"
  }}
]

Material:
{text}
"""

        raw = generate_questions(prompt)
        clean = sanitize_ai_response(raw)

        try:
            start = clean.find('[')
            end = clean.rfind(']')
            mcqs = json.loads(clean[start:end+1])
            if not isinstance(mcqs, list):
                raise ValueError("Response is not a list")

            filtered = []
            for item in mcqs:
                if (
                    isinstance(item, dict)
                    and "question" in item
                    and "options" in item
                    and "answer" in item
                    and isinstance(item["options"], list)
                    and len(item["options"]) == 4
                ):
                    filtered.append(item)
                if len(filtered) == num:
                    break

            if len(filtered) < num:
                return f"\u26a0\ufe0f Only {len(filtered)} questions generated. Try reducing the requested number."

            return render_template('mcq_exam.html', questions_json=json.dumps(filtered))

        except Exception as e:
            with open("broken_mcq_log.txt", "a", encoding="utf-8") as log:
                log.write(raw + "\n\n")
            return f"\u274c MCQ Generation Failed: Invalid JSON\n\nRaw response:\n{raw}"

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

if __name__ == '__main__':
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

