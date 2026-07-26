from flask import Flask, render_template, request, redirect, url_for,request, jsonify,session
from database import get_db_connection
from werkzeug.utils import secure_filename
import google.generativeai as genai
import cloudinary
import cloudinary.uploader
import os
from dotenv import load_dotenv

app=Flask(__name__)

app.secret_key = os.getenv("SECRET_KEY")

load_dotenv()

cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET")
)

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

model = genai.GenerativeModel("gemini-2.5-flash")

app.config['IMAGE_UPLOAD_FOLDER'] = 'static/uploads/images'
app.config['VOICE_UPLOAD_FOLDER'] = 'static/uploads/voices'

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/citizen-login', methods=['GET', 'POST'])
def citizen_login():

    if request.method == 'POST':

        email = request.form['email']
        password = request.form['password']


        conn = get_db_connection()

        cursor = conn.cursor(dictionary=True)

        cursor.execute(
            "SELECT * FROM CITIZENS WHERE email=%s AND password=%s",
            (email, password)
        )


        citizen = cursor.fetchone()

        cursor.close()
        conn.close()

        if citizen:
            session["citizen_id"] = citizen["CITIZEN_ID"]
            session["citizen_name"] = citizen["NAME"]
            session["citizen_email"] = citizen["EMAIL"]
            session["constituency"] = citizen["CONSTITUENCY"]
            session["district"] = citizen["DISTRICT"]
            session["state"] = citizen["STATE"]
            return redirect(url_for('citizen_dashboard'))
        else:
            return "Invalid Email or Password"

    return render_template('citizen-login.html')

@app.route('/citizen-register',methods=['GET','POST'])
def citizen_register():
    if request.method=='POST':

        name=request.form['name']
        email=request.form['email']
        mobile_number=request.form['mobile_number']
        password=request.form['password']
        confirm_password=request.form['confirm_password']
        state=request.form['state']
        district=request.form['district']
        constituency=request.form['constituency']
       

        if password!=confirm_password:
            return "Password do not match"

        conn=get_db_connection()
        cursor=conn.cursor()

        cursor.execute("""INSERT INTO CITIZENS 
        (name,email,mobile_number,password,state,district,constituency)
        VALUES(%s,%s,%s,%s,%s,%s,%s)""",
        (name,email,mobile_number,password,state,district,constituency))

        conn.commit()
        
        cursor.close()
        conn.close()

        return redirect(url_for('citizen_login'))

    return render_template('citizen-register.html')


@app.route('/citizen-dashboard')
def citizen_dashboard():

    if "citizen_id" not in session:
        return redirect(url_for("citizen_login"))

    conn=get_db_connection()
    cursor = conn.cursor(dictionary=True)

    citizen_id = session["citizen_id"]

    cursor.execute("""
    SELECT
        title,
        category,
        status,
        created_at
    FROM SUGGESTIONS
    WHERE citizen_id=%s
    ORDER BY created_at DESC
    LIMIT 5
    """, (citizen_id,))

    recent_suggestions = cursor.fetchall()
    
    

    cursor.execute("""
    SELECT
        title,
        category,
        ai_priority_score,
        status
    FROM SUGGESTIONS
    ORDER BY ai_priority_score DESC
    LIMIT 5
    """)

    community_updates = cursor.fetchall()

    # Total Submitted
    cursor.execute("""
    SELECT COUNT(*) AS total
    FROM SUGGESTIONS
    WHERE citizen_id=%s
    """, (citizen_id,))
    total_submitted = cursor.fetchone()["total"]

    # Pending
    cursor.execute("""
    SELECT COUNT(*) AS pending
    FROM SUGGESTIONS
    WHERE citizen_id=%s
    AND status='Pending'
    """, (citizen_id,))
    pending = cursor.fetchone()["pending"]

    # Resolved
    cursor.execute("""
    SELECT COUNT(*) AS resolved
    FROM SUGGESTIONS
    WHERE citizen_id=%s
    AND status='Resolved'
    """, (citizen_id,))
    resolved = cursor.fetchone()["resolved"]

    # My Suggestions (same as total submitted)
    my_suggestions = total_submitted

    cursor.close()
    conn.close()
    
    return render_template(
    'citizen-dashboard.html',

    recent_suggestions=recent_suggestions,
    community_updates=community_updates,

    citizen_name=session["citizen_name"],
    citizen_email=session["citizen_email"],
    constituency=session["constituency"],
    district=session["district"],
    state=session["state"],

    my_suggestions=my_suggestions,
    pending=pending,
    resolved=resolved,
    total_submitted=total_submitted
    )


@app.route('/submit-suggestion', methods=['GET', 'POST'])
def submit_suggestion():

    if "citizen_id" not in session:
        return redirect(url_for("citizen_login"))

    citizen_id = session["citizen_id"]

    if request.method == 'POST':

        category = request.form['category']
        title = request.form['title']
        description = request.form['description']
        latitude = request.form.get("latitude")
        longitude = request.form.get("longitude")

        # ---------------- AI ANALYSIS ----------------

        prompt = f"""
        You are an AI assistant for a citizen grievance portal.

        Analyze this suggestion.

        Category: {category}
        Title: {title}
        Description: {description}

        Return ONLY in this format:

        AI_CATEGORY:
        PRIORITY_SCORE:
        SUMMARY:

        Priority score must be between 1 and 100.
        Assign a priority score using these rules:

        90-100 : Emergency, immediate danger to citizens
        70-89 : High priority, should be resolved soon
        40-69 : Medium priority
        10-39 : Low priority

        Return only an integer.

        AI category should be one of:
        Roads
        Water
        Electricity
        Healthcare
        Education
        Environment
        Public Safety
        Other

        Summary should be 2 lines.
        """

        response = model.generate_content(prompt)

        ai_output = response.text

        lines = ai_output.strip().split("\n")

        ai_category = ""
        ai_priority_score = 0
        ai_summary = ""

        for line in lines:

            if line.startswith("AI_CATEGORY:"):
                ai_category = line.replace("AI_CATEGORY:", "").strip()

            elif line.startswith("PRIORITY_SCORE:"):
                ai_priority_score = int(
                    line.replace("PRIORITY_SCORE:", "").strip()
                )

            elif line.startswith("SUMMARY:"):
                ai_summary = line.replace("SUMMARY:", "").strip()

        # ---------------- FORM DATA ----------------

        location = request.form['location']

        image = request.files.get('image')
        voice = request.files.get('voice')

        # Default empty URLs
        image_path = ""
        voice_path = ""

        # ---------------- CLOUDINARY IMAGE UPLOAD ----------------

        if image and image.filename != "":

            image_result = cloudinary.uploader.upload(
                image,
                folder="peoples_priority_ai/images",
                resource_type="image"
            )

            image_path = image_result.get("secure_url", "")

        # ---------------- CLOUDINARY VOICE UPLOAD ----------------

        if voice and voice.filename != "":

            voice_result = cloudinary.uploader.upload(
                voice,
                folder="peoples_priority_ai/voices",
                resource_type="video"
            )

            voice_path = voice_result.get("secure_url", "")

        # ---------------- DATABASE INSERT ----------------

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
        INSERT INTO SUGGESTIONS
        (
            citizen_id,
            title,
            category,
            ai_category,
            ai_priority_score,
            ai_summary,
            description,
            location,
            latitude,
            longitude,
            image_path,
            voice_path,
            status
        )
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (
            citizen_id,
            title,
            category,
            ai_category,
            ai_priority_score,
            ai_summary,
            description,
            location,
            latitude,
            longitude,
            image_path,
            voice_path,
            "Pending"
        ))

        conn.commit()

        cursor.close()
        conn.close()

        return redirect(url_for('citizen_dashboard'))

    return render_template(
        'submit-suggestion.html',
        citizen_name=session.get("citizen_name"),
        citizen_email=session.get("citizen_email")
    )

@app.route('/admin-login', methods=['GET', 'POST'])
def admin_login():

    if request.method == 'POST':

        email = request.form['email']
        password = request.form['password']

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute(
            "SELECT * FROM ADMINS WHERE email=%s AND password=%s",
            (email, password)
        )

        admin = cursor.fetchone()

        cursor.close()
        conn.close()

        if admin:
            session["admin_id"]=admin["ADMIN_ID"]
            session["admin_name"]=admin["NAME"]
            session["admin_email"]=admin["EMAIL"]
            return redirect(url_for('admin_dashboard'))
        else:
            return "Invalid Admin Credentials"

    return render_template('admin-login.html')

@app.route('/admin-dashboard')
def admin_dashboard():

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Total Suggestions
    cursor.execute("SELECT COUNT(*) AS total FROM SUGGESTIONS")
    total_suggestions = cursor.fetchone()["total"]

    # Pending Review
    cursor.execute("SELECT COUNT(*) AS pending FROM SUGGESTIONS WHERE status='Pending'")
    pending_review = cursor.fetchone()["pending"]

    # High Priority (AI score >= 80)
    cursor.execute("SELECT COUNT(*) AS total FROM SUGGESTIONS WHERE AI_PRIORITY_SCORE >= 80")
    high_priority = cursor.fetchone()["total"]
   

    # Resolved Suggestions
    cursor.execute("SELECT COUNT(*) AS resolved FROM SUGGESTIONS WHERE status='Resolved'")
    resolved = cursor.fetchone()["resolved"]

    cursor.execute("""
    SELECT
        suggestion_id,
        title,
        category,
        description,
        location,
        status,
        image_path,
        voice_path,
        ai_category,
        ai_priority_score,
        ai_summary
    FROM SUGGESTIONS
    ORDER BY ai_priority_score DESC
    """)

    suggestions = cursor.fetchall()

    cursor.execute("""
    SELECT
        category,
        COUNT(*) AS total
    FROM SUGGESTIONS
    GROUP BY category
    ORDER BY total DESC
    """)

    category_stats = cursor.fetchall()

    for item in category_stats:
        item["bar_height"] = min(item["total"] * 30, 180)

    cursor.execute("""
    SELECT
        title,
        category,
        latitude,
        longitude,
        ai_priority_score
    FROM SUGGESTIONS
    WHERE latitude IS NOT NULL
    AND longitude IS NOT NULL
    """)

    map_data = cursor.fetchall()

    cursor.close()
    conn.close()

    

    return render_template(
    "admin-dashboard.html",
    suggestions=suggestions,
    total_suggestions=total_suggestions,
    pending_review=pending_review,
    high_priority=high_priority,
    resolved=resolved,
    category_stats=category_stats,
    admin_name=session["admin_name"],
    admin_email=session["admin_email"],
    map_data=map_data
    )


@app.route("/run-simulation", methods=["POST"])
def run_simulation():

    data = request.get_json()

    budget = float(data["budget"])
    category = data["category"]

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
    SELECT AVG(ai_priority_score) AS avg_score
    FROM SUGGESTIONS
    WHERE category = %s
    """, (category,))

    row = cursor.fetchone()

    avg_score = float(row["avg_score"]) if row["avg_score"] else 50.0

    cursor.close()
    conn.close()

    estimated_cost = round(budget * (avg_score / 100), 2)

    remaining_budget = round(budget - estimated_cost, 2)

    citizens = int(estimated_cost * 10000)

    days = max(
        20,
        int(120 - budget * 4 - avg_score / 2)
    )

    improvement = int(avg_score)

    return jsonify({
        "citizens": f"{citizens:,}",
        "cost": f"₹ {estimated_cost} Crore",
        "remaining_budget": f"₹ {remaining_budget} Crore",
        "days": days,
        "improvement": f"{improvement}%"
    })

@app.route('/update-status', methods=['POST'])
def update_status():

    data = request.get_json()

    suggestion_id = data['suggestion_id']
    status = data['status']

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE SUGGESTIONS
        SET STATUS = %s
        WHERE suggestion_id = %s
    """, (status, suggestion_id))

    conn.commit()

    cursor.close()
    conn.close()

    return {"success": True}

if __name__=="__main__":
    app.run(debug=True)
