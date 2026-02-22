import os
import sqlite3
import json
import random
import string
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from datetime import datetime
from groq import Groq
from dotenv import load_dotenv

# تحميل متغيرات البيئة (تأكدي من وجود ملف .env فيه مفتاح GROQ_API_KEY)
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'malak_smart_study_pro_2026')

# إعداد عميل Groq
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# ==========================================
# 1. إعداد قاعدة البيانات وتوليد 5000 كود (4 رموز)
# ==========================================
def init_db():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
   
    # جدول المستخدمين: يحفظ بيانات التسجيل، الروتين الأسبوعي، ونقاط الضعف
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (code TEXT PRIMARY KEY, user_data TEXT, routine_data TEXT, weakness TEXT)''')
   
    # جدول الأكواد: لإدارة عملية تسجيل الدخول
    c.execute('''CREATE TABLE IF NOT EXISTS codes
                 (code TEXT PRIMARY KEY, is_used INTEGER DEFAULT 0)''')
   
    # التحقق إذا كانت الأكواد موجودة مسبقاً
    c.execute('SELECT COUNT(*) FROM codes')
    if c.fetchone()[0] == 0:
        print("جاري توليد 5000 كود وصول (4 رموز)...")
        generated_codes = set()
        # اختيار حروف كبيرة وأرقام
        chars = string.ascii_uppercase + string.digits
       
        while len(generated_codes) < 5000:
            # توليد كود من 4 رموز فقط كما طلبتِ
            code = ''.join(random.choices(chars, k=4))
            generated_codes.add(code)
       
        # إدخال الأكواد في قاعدة البيانات
        c.executemany('INSERT INTO codes (code, is_used) VALUES (?, 0)', [(c,) for c in generated_codes])
       
        # حفظ نسخة في ملف نصي لسهولة توزيعها
        with open('all_student_codes.txt', 'w', encoding='utf-8') as f:
            f.write("=== أكواد طلاب منصة Smart Study 2026 (4 رموز) ===\n")
            for i, code in enumerate(sorted(list(generated_codes)), 1):
                f.write(f"{i}- {code}\n")
       
        conn.commit()
    conn.close()

# تشغيل التهيئة
init_db()

# ==========================================
# 2. المسارات (Routes)
# ==========================================

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        user_code = request.form.get('access_code', '').strip().upper()
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
       
        # 1. هل الكود مسجل لمستخدم قديم؟ (يدخل مباشرة للداشبورد)
        c.execute('SELECT code FROM users WHERE code = ?', (user_code,))
        if c.fetchone():
            session['auth'], session['user_code'] = True, user_code
            conn.close()
            return redirect(url_for('dashboard'))
           
        # 2. هل الكود جديد وصحيح؟ (ينتقل للتسجيل)
        c.execute('SELECT is_used FROM codes WHERE code = ? AND is_used = 0', (user_code,))
        if c.fetchone():
            session['auth'], session['user_code'] = True, user_code
            conn.close()
            return redirect(url_for('register'))
           
        conn.close()
        return render_template('index.html', error="الكود غير صحيح أو تم استخدامه مسبقاً!")
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if not session.get('auth'): return redirect(url_for('index'))
    if request.method == 'POST':
        session['user_data'] = request.form.to_dict()
        return redirect(url_for('schedule_info'))
    return render_template('register.html')

@app.route('/schedule_info', methods=['GET', 'POST'])
def schedule_info():
    if not session.get('auth'): return redirect(url_for('index'))
    if request.method == 'POST':
        session['routine'] = request.form.to_dict()
        return redirect(url_for('exam'))
    return render_template('schedule_info.html')

@app.route('/exam')
def exam():
    if not session.get('auth'): return redirect(url_for('index'))
    user = session.get('user_data', {})
   
    # طلب 10 أسئلة MCQ بناءً على المرحلة الدراسية المختارة
    prompt = f"ولد 10 أسئلة MCQ متنوعة لمستوى {user.get('grade')} {user.get('stage')} منهج مصر. الرد JSON فقط: {{\"questions\":[{{\"q\":\"..\",\"a\":[\"..\"],\"correct\":\"..\",\"subject\":\"..\"}}]}}"
    try:
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role":"user","content":prompt}],
            response_format={"type":"json_object"}
        )
        session['questions'] = json.loads(completion.choices[0].message.content).get('questions', [])
    except:
        session['questions'] = []
    return render_template('exam.html', questions=session['questions'])

@app.route('/analyze_results', methods=['POST'])
def analyze_results():
    if not session.get('auth'): return redirect(url_for('index'))
   
    answers = request.form.to_dict()
    questions = session.get('questions', [])
   
    # مقارنة الإجابات لتحديد المواد التي يحتاج الطالب لتقويتها
    weakness = list(set([q['subject'] for i, q in enumerate(questions) if answers.get(f'q{i}') != q['correct']]))
   
    # حفظ كل البيانات في قاعدة البيانات
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO users VALUES (?, ?, ?, ?)',
              (session['user_code'], json.dumps(session['user_data']), json.dumps(session['routine']), json.dumps(weakness)))
    c.execute('UPDATE codes SET is_used = 1 WHERE code = ?', (session['user_code'],))
    conn.commit()
    conn.close()
   
    return redirect(url_for('dashboard'))

@app.route('/dashboard')
def dashboard():
    if not session.get('auth'): return redirect(url_for('index'))
   
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('SELECT user_data, routine_data, weakness FROM users WHERE code = ?', (session['user_code'],))
    data = c.fetchone()
    conn.close()
   
    if not data: return redirect(url_for('register'))
   
    user_info = json.loads(data[0])
    routine = json.loads(data[1])
    weakness = json.loads(data[2])
   
    # تحديد اليوم الحالي لعرض الجدول المناسب
    days_map = {
        "Saturday":"السبت", "Sunday":"الأحد", "Monday":"الاثنين",
        "Tuesday":"الثلاثاء", "Wednesday":"الأربعاء", "Thursday":"الخميس", "Friday":"الجمعة"
    }
    today_ar = days_map.get(datetime.now().strftime("%A"), "السبت")
   
    # جلب روتين الطالب المحفوظ لهذا اليوم
    today_routine = routine.get(f'routine_{today_ar}', 'لا توجد التزامات مسجلة اليوم')

    # توليد الجدول الدراسي اليومي عبر الذكاء الاصطناعي بتنسيق احترافي
    prompt = f"""
    أنت خبير تنظيم وقت. صمم جدول مذاكرة احترافي ليوم ({today_ar}) للطالب {user_info.get('name')} في {user_info.get('grade')}.
    المعطيات:
    - التزامات الطالب اليوم (مدرسة/دروس): {today_routine}
    - مواد ضعيفة يجب تكثيفها: {weakness}
   
    المطلوب: جدول HTML Bootstrap (class: table table-hover table-bordered table-striped text-center).
    وزع أوقات المذاكرة والراحة والصلاة بذكاء. الرد كود HTML فقط.
    """
   
    try:
        completion = client.chat.completions.create(model="llama-3.3-70b-versatile", messages=[{"role":"user","content":prompt}])
        plan = completion.choices[0].message.content.replace('```html', '').replace('```', '')
    except:
        plan = "<div class='alert alert-danger'>نعتذر، حدث خطأ أثناء توليد جدول اليوم.</div>"
   
    return render_template('dashboard.html', plan=plan, name=user_info.get('name'), day=today_ar)

@app.route('/ask-bot', methods=['POST'])
def ask_bot():
    msg = request.json.get('message', '')
    try:
        comp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role":"user","content": f"أنت مساعد دراسي ذكي، أجب باختصار وتنسيق واضح: {msg}"}]
        )
        return jsonify({'reply': comp.choices[0].message.content})
    except:
        return jsonify({'reply': "عذراً، لا أستطيع الرد حالياً. حاول لاحقاً!"})

if __name__ == '__main__':
    # تشغيل السيرفر
    app.run(host='0.0.0.0',port=5000)