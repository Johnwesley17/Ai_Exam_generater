from flask import Flask, render_template, request, redirect, session, send_file
from werkzeug.security import generate_password_hash, check_password_hash
from fpdf import FPDF
import fitz  # PyMuPDF
import os, json, tempfile, uuid, re
import mysql.connector
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")

UPLOAD_FOLDER = 'uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
client = Groq(api_key=GROQ_API_KEY)

def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv("MYSQL_HOST"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.getenv("MYSQL_USER"),
        password=os.getenv("MYSQL_PASSWORD"),
        database=os.getenv("MYSQL_DB"),
        ssl_ca=os.getenv("MYSQL_SSL_CA")
    )

def extract_text(pdf_path):
    doc = fitz.open(pdf_path)
    return " ".join([page.get_text() for page in doc]).strip()

def generate_questions(prompt):
    response = client.chat.completions.create(
        model="llama3-8b-8192",
        messages=[
            {"role": "system", "content": "You are an exam question generator."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.7,
        max_tokens=1500
    )
    return response.choices[0].message.content.strip()

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
    if 'user_id' in session:
        return redirect('/')
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = generate_password_hash(request.form['password'])

        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("INSERT INTO users (username, email, password) VALUES (%s, %s, %s)", (username, email, password))
            conn.commit()
            cur.close()
            conn.close()
            return redirect('/login')
        except Exception as e:
            return f"❌ Signup Failed: {str(e)}"
    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect('/')
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
    text = text[:3000]  # ✅ Prevent token overflow with Groq

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
        font_path = 'fonts/DejaVuSans.ttf'
        bold_path = 'fonts/DejaVuSans-Bold.ttf'
        if not os.path.exists('fonts'):
            os.makedirs('fonts')
        pdf.add_font('DejaVu', '', font_path, uni=True)
        pdf.add_font('DejaVu', 'B', bold_path, uni=True)
        pdf.set_font("DejaVu", size=14)
        pdf.add_page()

        for line in heading.strip().split("\n"):
            pdf.multi_cell(0, 10, line.strip(), align="C")
        pdf.ln(5)

        for sec in sorted_sections:
            try:
                title = sec.get('title', 'Section')
                count = int(sec.get('count', 0) or 0)
                difficulty = sec.get('difficulty', 'medium')
                marks = sec.get('marks', '2')
                if count <= 0:
                    continue

                prompt = f"""
You are a question paper generator.
Generate exactly {count} distinct {difficulty}-level questions worth {marks} marks each from the material below.

⚠️ Output numbered questions only. No headers. No explanations.

Material:
{text}
"""
                ai_response = generate_questions(prompt)

                print(f"\n--- AI Response for {title} ---\n{ai_response}\n--- End ---")

                lines = ai_response.strip().split('\n')
                questions = [line.strip() for line in lines if re.match(r"^\d+[\).]?\s", line)]
                if len(questions) > count:
                    questions = questions[:count]

                pdf.set_font("DejaVu", style='B', size=12)
                pdf.set_fill_color(240, 240, 240)
                pdf.cell(0, 10, title, ln=True, fill=True)
                pdf.set_font("DejaVu", size=11)

                for q in questions:
                    pdf.multi_cell(0, 10, q, border=1)
                    pdf.ln(1)

            except Exception as e:
                print("⚠️ Section error:", e)

        out_path = os.path.join(tempfile.gettempdir(), "written_exam.pdf")
        pdf.output(out_path)
        return send_file(out_path, as_attachment=True)

    elif exam_type == 'mcq':
        num = int(request.form.get('num_questions', 0) or 0)
        if num <= 0:
            return "Please enter a valid number of MCQs."

        prompt = f"""
You are a test-set generator. Return exactly {num} multiple-choice questions in JSON format.

Only return JSON. No explanations. Format:
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
            if isinstance(mcqs, list):
                mcqs = mcqs[:num]
            else:
                raise ValueError("Not a list")
        except Exception as e:
            with open("broken_mcq_log.txt", "a", encoding="utf-8") as log:
                log.write(raw + "\n\n")
            return f"❌ MCQ Generation Failed. Error: {e}"

        return render_template('mcq_exam.html', questions_json=json.dumps(mcqs))

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

if __name__ == '__main__':
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
