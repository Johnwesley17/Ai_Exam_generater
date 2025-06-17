
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
    text = re.sub(r"
json|
", "", text)
    return text.strip()

# Home route
@app.route('/')
def home():
    if 'user_id' not in session:
        return redirect('/login')
    return render_template('index.html')

# Signup
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
            return f"❌ Signup Failed: {str(e)}"
    return render_template('signup.html')

# Login
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
            return f"❌ Login Failed: {str(e)}"
    return render_template('login.html')

# Exam Generator Route
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

    # ✅ WRITTEN EXAM PDF OUTPUT
    if exam_type == 'written':
        heading = request.form['heading']
        sections = {}
        for key in request.form:
            match = re.match(r"sections\[(\d+)\]\[(\w+)\]", key)
            if match:
                index, field = int(match.group(1)), match.group(2)
                sections.setdefault(index, {})[field] = request.form[key]

        sorted_sections = [sections[i] for i in sorted(sections)]

        pdf = FPDF()
        pdf.set_margins(15, 15, 15)
        pdf.add_font('DejaVu', '', 'fonts/DejaVuSans.ttf', uni=True)
        pdf.add_font('DejaVu', 'B', 'fonts/DejaVuSans-Bold.ttf', uni=True)
        pdf.set_font("DejaVu", size=14)
        pdf.add_page()
        for line in heading.strip().split("\n"):
            pdf.multi_cell(0, 10, line.strip(), align="C")
        pdf.ln(5)

        for sec in sorted_sections:
            try:
                title = sec.get('title', 'Section').strip()
                count = int(sec.get('count', 0))
                difficulty = sec.get('difficulty', 'medium').strip().lower()
                marks = sec.get('marks', '2').strip()
                if count <= 0:
                    continue

                prompt = f"""
You are a university exam paper generator.

Generate exactly {count} distinct {difficulty}-level questions, each worth {marks} marks, from the material below.

⚠️ Output only numbered questions (e.g., 1., 2., 3.). No extra text, no explanations, no headers.

Material:
{text}
"""
                ai_response = generate_questions(prompt)
                if not ai_response.strip():
                    continue

                # Filter exact number of valid numbered questions
                questions = []
                for line in ai_response.strip().split("\n"):
                    line = line.strip()
                    if re.match(r"^\d+[\).]?\s", line):
                        questions.append(line)
                    if len(questions) >= count:
                        break

                pdf.set_font("DejaVu", style='B', size=12)
                pdf.set_fill_color(240, 240, 240)
                pdf.cell(0, 10, title, ln=True, fill=True)
                pdf.set_font("DejaVu", size=11)

                for q in questions:
                    pdf.multi_cell(0, 10, q, border=1)
                    pdf.ln(1)

            except Exception as e:
                print(f"⚠️ Error in section: {e}")
                continue

        out_path = os.path.join(tempfile.gettempdir(), "written_exam.pdf")
        pdf.output(out_path)
        return send_file(out_path, as_attachment=True)

    # ✅ MCQ Exam Route
    elif exam_type == 'mcq':
        num = int(request.form.get('num_questions', 0) or 0)
        if num <= 0:
            return "Please enter a valid number of MCQs."

        prompt = f"""
You are a test-set generator. Based on the study material below, return exactly {num} multiple-choice questions.

⚠️ Return ONLY valid JSON. No explanations.

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
        except Exception as e:
            with open("broken_mcq_log.txt", "a", encoding="utf-8") as log:
                log.write(raw + "\n\n")
            return f"❌ MCQ Generation Failed: Invalid JSON\n\nRaw response:\n{raw}"

        return render_template('mcq_exam.html', questions_json=json.dumps(mcqs))

# Logout
@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

# Run the app
if __name__ == '__main__':
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
