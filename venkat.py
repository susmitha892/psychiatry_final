import os
from flask import Flask, render_template, request, redirect, url_for, flash, make_response, send_from_directory,Blueprint
from flask_sqlalchemy import SQLAlchemy
import os
import pandas as pd
import matplotlib.pyplot as plt
from flask_migrate import Migrate
import pytz
from datetime import datetime, date
import uuid
from flask import jsonify, abort
import requests
from sqlalchemy.types import TypeDecorator, Text
from werkzeug.security import generate_password_hash, check_password_hash
from flask import session
from functools import wraps
from werkzeug.utils import secure_filename
from radiology import radiology_bp
from labs import labs_bp # <-- Import the new labs Blueprint
import secrets
import matplotlib
matplotlib.use('Agg') 
import matplotlib.pyplot as plt 
# ... rest of your imports
from io import BytesIO
try:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False
    print("ReportLab not installed. PDF generation will be disabled.")


app = Flask(__name__)

# API Key
# ====================================================================
# Note: In a real application, this should be stored in a config file
# or environment variable, not hardcoded.
API_KEY = "admin-4567-fghij-02"

def check_api_key():
    """Checks for the presence and validity of the X-API-Key header."""
    key = request.headers.get('X-API-Key')
    if key != API_KEY:
        abort(401, description="Invalid API Key")

# ====================================================================
# Sample In-Memory Patient Database
# ====================================================================
# This is a dictionary that acts as a simple database for demonstration.
# Corrected data structure
patients = {
    "UHID001": {
        "details": {
            "chief_complaints": [
                "Depressed mood"
            ],
            "cognitive_functions": {
                "memory": "Intact short-term and long-term memory.",
                "orientation": "Oriented to person, place, and time."
            },
            "department": "Psychiatry",
            "diagnosis": "Major Depressive Disorder",
            "history_of_illness": "Patient reports persistent low mood for 3 months following a relationship breakup",
            "medications": {
                "dose": "50mg",
                "frequency": "Daily",
                "instructions": "Take orally, with or without food.",
                "name": "Sertraline (Zoloft)"
            },
            "mental_status_examination": {
                "appearance_and_behavior": "Grooming and hygiene appear adequate.",
                "mood": "Reports feeling",
                "speech": "Normal rate"
            },
            "record_id": "1",
            "scales_and_scores": {
                "phq-9": "18 (Moderately severe depression)"
            },
            "treatment": [
                "Psychotherapy (Cognitive Behavioral Therapy)"
            ]
        }
    }
}
# ====================================================================
# API Endpoints
# ====================================================================
# Route for retrieving a patient's details by UHID
#Route for retrieving a patient's details by UHID
@app.route('/api/patient/<string:uhid>', methods=['GET'])
def get_patient(uhid):
    """
    Retrieves patient details based on UHID provided in the URL.
    Example URL: http://127.0.0.1:5000/api/patient/UHID001
    """
    check_api_key() # Check for the API key first
    
    patient = patients.get(uhid)
    if not patient:
        return jsonify({"error": "Patient not found"}), 404

    # New code to get the desired output format
    # The 'details' object is the entire 'patient' dictionary in this case
    return jsonify({"details": patient})

# Route for creating a new patient
@app.route('/api/patient/add', methods=['POST'])
def add_patient():
    """
    Adds a new patient to the database.
    Requires JSON data in the request body.
    """
    check_api_key() # Check for the API key first
    data = request.json
    
    if not data or 'uhid' not in data or 'name' not in data:
        return jsonify({"error": "Missing required fields (uhid, name)"}), 400
    
    uhid = data['uhid']
    if uhid in patients:
        return jsonify({"error": "Patient with this UHID already exists"}), 409
        
    patients[uhid] = {
        "name": data['name'],
        "age": data.get('age'),
        "condition": data.get('condition', 'N/A')
    }
    
    return jsonify({"message": "Patient created successfully", "uhid": uhid}), 201

# New configuration: Use environment variable for database connection
# This is crucial for deployment on Render
# It will fall back to SQLite for local development if the variable is not set
DATABASE_URL = os.environ.get('DATABASE_URL')
BASE_DIR = os.path.abspath(os.path.dirname(__file__))

if DATABASE_URL:
    # Render's database URL might use 'postgres://' which SQLAlchemy 1.4+ dislikes.
    # We replace it with 'postgresql://'
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    
    app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
else:
    # Fallback to a local SQLite file for development
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(BASE_DIR, 'instance', 'app.db')

# Ensure the instance folder exists for local development
if not os.path.exists(os.path.join(BASE_DIR, 'instance')):
    os.makedirs(os.path.join(BASE_DIR, 'instance'))





app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'your_secret_key'
db = SQLAlchemy(app)
app.secret_key = secrets.token_hex(16)
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_PERMANENT'] = True


# Add this configuration for file uploads
UPLOAD_FOLDER = 'static/uploads'
# Create the directory if it doesn't exist
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
migrate = Migrate(app, db)

# Define a directory to save the chart images
CHART_DIR = os.path.join(app.root_path, 'static', 'charts')
if not os.path.exists(CHART_DIR):
    os.makedirs(CHART_DIR)
# ====================================================================
# Database Models
# ====================================================================
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    # Add a role column to the User model
    role = db.Column(db.String(20), default='doctor', nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
class Patient(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    
    # Personal Information
    name = db.Column(db.String(100), nullable=False)
    age = db.Column(db.Integer)
    gender = db.Column(db.String(10))
    mobile_no = db.Column(db.String(15))
    email = db.Column(db.String(120))
    
    # Vital Signs
    # The 'name' attribute in the HTML input tags are used to define the variables
    bp_sys = db.Column(db.Integer)
    bp_dia = db.Column(db.Integer)
    sugar = db.Column(db.String(20)) # Using string for flexibility
    height = db.Column(db.String(20))
    weight = db.Column(db.String(20))
    temperature = db.Column(db.String(20))

    # Record Information
    uhid = db.Column(db.String(20), unique=True, nullable=False)
    registration_date = db.Column(db.DateTime, default=datetime.utcnow)

    
    # New columns for analytics
    abnormal_bp = db.Column(db.Boolean, default=False)
    abnormal_sugar = db.Column(db.Boolean, default=False)
    abnormal_temp = db.Column(db.Boolean, default=False)


    
    assessment_history = db.relationship('Assessment', backref='patient', lazy=True)
    treatment_history = db.relationship('Treatment', backref='patient', lazy=True)
lab_report_history = db.relationship('LabReport', backref='patient', lazy=True)

class Assessment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    uhid = db.Column(db.String(20), db.ForeignKey('patient.uhid'), nullable=False)
    visit_date = db.Column(db.Date, nullable=True, default=date.today)
    demographics = db.Column(db.JSON)
    chief_complaints = db.Column(db.JSON)
    history = db.Column(db.JSON)   # ✅ for storing history dict
    personal_history = db.Column(db.JSON)
    premorbid_personality = db.Column(db.JSON)
    cognitive_functions = db.Column(db.JSON) 
    physical_exam = db.Column(db.JSON)
    mental_status = db.Column(db.JSON)
    previous_history = db.Column(db.JSON)
    scales = db.Column(db.JSON)
    review_patient = db.Column(db.String(3))
    review_patient_details = db.Column(db.Text)
    referral = db.Column(db.String(3))
    referral_details = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Treatment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    uhid = db.Column(db.String(20), db.ForeignKey('patient.uhid'), nullable=False)
    visit_date = db.Column(db.Date, nullable=True, default=date.today)
    diagnosis = db.Column(db.JSON)
    psychotherapy = db.Column(db.JSON)
    medications = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class LabReport(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    uhid = db.Column(db.String(20), db.ForeignKey('patient.uhid'), nullable=False)
    visit_date = db.Column(db.Date, nullable=True, default=date.today)
    tests = db.Column(db.JSON)
    scans = db.Column(db.JSON)
    uploaded_files = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False) # Add this line

class JSONB(TypeDecorator):
    impl = Text
    def process_bind_param(self, value, dialect):
        if value is not None:
            return json.dumps(value)
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            return json.loads(value)
        return value
    

def upgrade():
    # Add the column, allowing it to be nullable for existing rows
    with op.batch_alter_table('assessment', schema=None) as batch_op:
        batch_op.add_column(sa.Column('visit_date', sa.Date(), nullable=True))

    # NOTE: If you need to populate existing rows with a value, you would do it here.
    # Example: op.execute('UPDATE assessment SET visit_date = "2023-01-01"')

    # Finally, alter the column to be NOT NULL
    with op.batch_alter_table('assessment', schema=None) as batch_op:
        batch_op.alter_column('visit_date',
                              existing_type=sa.Date(),
                              nullable=False)
        
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def role_required(role_name):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'logged_in' not in session:
                flash('Please log in to access this page.', 'warning')
                return redirect(url_for('login'))
            if 'role' not in session or session['role'] != role_name:
                flash(f'Access denied. You must be a {role_name}.', 'danger')
                return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

    # Exit or handle the error gracefully, as the PDF feature won't work
# @app.before_first_request # REMOVED
def create_tables():
    db.create_all()

def generate_uhid():
    """Generates the next sequential UHID (e.g., UHID001, UHID002)."""
    last_patient = Patient.query.order_by(Patient.id.desc()).first()
    if last_patient:
        try:
            # Attempt to get the last sequential UHID
            last_id = int(last_patient.uhid.replace('UHID', ''))
            new_id = last_id + 1
            return f"UHID{new_id:03}"
        except ValueError:
            # If the last UHID is not in the expected format (e.g., a UUID),
            # start the sequence from the beginning.
            return "UHID001"
    else:
        # If there are no patients, start with UHID001
        return "UHID001"
# In your app.py file

@app.route('/')
@login_required
def dashboard():
    # Redirect doctors to their specific dashboard
    if session.get('user_role') == 'doctor':
        return redirect(url_for('psychiatry_dashboard'))
    total_patients = Patient.query.count()
    new_patients_count = Patient.query.filter(Patient.registration_date >= datetime.now().date()).count()
    review_patients_count = total_patients - new_patients_count
    abnormal_vitals_count = Assessment.query.filter(
        (Assessment.physical_exam.like('%Abnormal BP%')) |
        (Assessment.physical_exam.like('%Abnormal Sugar%')) |
        (Assessment.physical_exam.like('%Abnormal Temp%'))
    ).count()
    stats = {
        'total_patients': total_patients,
        'new_patients': new_patients_count,
        'review_patients': review_patients_count,
        'abnormal_vitals_count': abnormal_vitals_count,
    }
    return render_template('dashboard.html', stats=stats)


# vinayaka.py

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        role = request.form.get('role') # Get the selected role from the form

        if User.query.filter_by(username=username).first():
            flash('Username already exists. Please choose a different one.', 'danger')
            return redirect(url_for('register'))

        # Use the role from the form
        new_user = User(username=username, role=role) 
        new_user.set_password(password)

        db.session.add(new_user)
        db.session.commit()

        flash('Registration successful! Please log in.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            session['logged_in'] = True
            session['username'] = user.username  # Store the username
            session['user_role'] = user.role      # Store the user's role
            flash('Logged in successfully!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password.', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    session.pop('username', None)
    session.pop('user_role', None)  # Clear the user role from the session
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

# In your app.py file

@app.route('/psychiatry_dashboard')
def psychiatry_dashboard():
    
    # Retrieve all patients
    all_patients = Patient.query.all()
    
    # Calculate statistics
    total_patients = len(all_patients)
    new_patients_count = Patient.query.filter(Patient.registration_date >= datetime.now().date()).count()
    review_patients_count = total_patients - new_patients_count
    
    # Calculate the count of patients with abnormal vitals
    abnormal_vitals_count = Assessment.query.filter(
        (Assessment.physical_exam.like('%Abnormal BP%')) |
        (Assessment.physical_exam.like('%Abnormal Sugar%')) |
        (Assessment.physical_exam.like('%Abnormal Temp%'))
    ).count()

    # Create the `stats` dictionary with all the data
    stats = {
        'total_patients': total_patients,
        'new_patients': new_patients_count,
        'review_patients': review_patients_count,
        'abnormal_vitals_count': abnormal_vitals_count 
    }
    
    # Pass the stats object and other variables to the template
    return render_template('psychiatry_dasboard.html', stats=stats, all_patients=all_patients)

# ====================================================================
# API Endpoints
# ====================================================================
@app.route('/patient-entry', methods=['GET', 'POST'])
def patient_entry():
    if request.method == 'POST':
        # Get data from the form
        name = request.form.get('patient_name')
        age = request.form.get('age', type=int) # Cast to int for comparisons
        gender = request.form.get('gender')
        mobile_no = request.form.get('mobile_no')
        email = request.form.get('email')
        
        # Get vital signs from the form
        bp_sys_str = request.form.get('bp_sys')
        bp_dia_str = request.form.get('bp_dia')
        sugar_str = request.form.get('sugar')
        height = request.form.get('height')
        weight = request.form.get('weight')
        temperature_str = request.form.get('temp') # Corrected to match HTML name
        
        # Generate the next sequential UHID
        uhid = generate_uhid()

        # Initialize abnormal flags
        abnormal_bp = False
        abnormal_sugar = False
        abnormal_temp = False

        # Check for abnormal vitals based on a simple hardcoded range
        # Note: In a real-world app, these ranges would be more dynamic
        try:
            # Blood Pressure (BP) check
            if bp_sys_str and bp_dia_str:
                bp_sys = int(bp_sys_str)
                bp_dia = int(bp_dia_str)
                if bp_sys > 140 or bp_dia > 90:
                    abnormal_bp = True
            
            # Blood Sugar check
            if sugar_str:
                sugar = int(sugar_str)
                if sugar < 70 or sugar > 180: # Example ranges for fasting/random
                    abnormal_sugar = True
            
            # Temperature check
            if temperature_str:
                temperature = float(temperature_str)
                if temperature < 97.0 or temperature > 99.0:
                    abnormal_temp = True

        except (ValueError, TypeError):
            # Handle cases where the form data is not a valid number
            flash('Invalid vital sign data provided.', 'danger')
            return redirect(url_for('patient_entry'))

        # Create a new patient object with all the data and the abnormal flags
        new_patient = Patient(
            uhid=uhid,
            name=name,
            age=age,
            gender=gender,
            mobile_no=mobile_no,
            email=email,
            bp_sys=bp_sys_str,
            bp_dia=bp_dia_str,
            sugar=sugar_str,
            height=height,
            weight=weight,
            temperature=temperature_str,
            abnormal_bp=abnormal_bp,
            abnormal_sugar=abnormal_sugar,
            abnormal_temp=abnormal_temp,
            registration_date=datetime.now() # This line was missing
        )
        
        # Save the patient to the database
        db.session.add(new_patient)
        db.session.commit()
        
        # Flash a success message
        flash(f'Patient {name} added successfully with UHID: {uhid}!', 'success')
        
        # Redirect after successful registration
        return redirect(url_for('psychiatry_dashboard'))
        
    return render_template('patient_entry.html')

# Note: If you are using the patient-registration route, you will also need to
# make the same change there.
@app.route('/patient-registration', methods=['GET', 'POST'])
def patient_registration():
    if request.method == 'POST':
        uhid = request.form.get('uhid')
        name = request.form.get('name')
        age = request.form.get('age')
        gender = request.form.get('gender')
        existing_patient = Patient.query.filter_by(uhid=uhid).first()
        if existing_patient:
            flash('UHID already exists. Please use a unique ID.', 'danger')
            return redirect(url_for('patient_registration'))
        new_patient = Patient(uhid=uhid, name=name, age=age, gender=gender)
        db.session.add(new_patient)
        db.session.commit()
        # **CORRECTED:** Redirect to the psychiatry dashboard after successful registration
        return redirect(url_for('psychiatry_dashboard'))
    return render_template('patient_entry.html')

@app.route('/review_patient', methods=['GET'])
@login_required
def review_patient():
    uhid = request.args.get('uhid')
    visiting_date_str = request.args.get('visiting_date')
    visiting_date = date.today() # Default to today's date
    error = None
    patient = None

    if visiting_date_str:
        try:
            visiting_date = datetime.strptime(visiting_date_str, '%Y-%m-%d').date()
        except ValueError:
            error = "Invalid date format. Please use YYYY-MM-DD."
            visiting_date = date.today() # Revert to today's date to prevent further errors

    if uhid:
        patient = Patient.query.filter_by(uhid=uhid).first()
        if not patient:
            error = "Patient not found. Please check the UHID."

    return render_template('review_patient.html', 
                           visiting_date=visiting_date.strftime('%Y-%m-%d'), 
                           patient=patient, 
                           error=error)


@app.route('/assessment_form/<uhid>', methods=['GET', 'POST'])
def assessment_form(uhid):
    # Check if the user is logged in
    if 'username' not in session:
        return redirect(url_for('login'))
    
    # Add this code to get the visiting_date from the URL
    visiting_date_str = request.args.get('visiting_date')
    visiting_date = datetime.strptime(visiting_date_str, '%Y-%m-%d').date() if visiting_date_str else date.today()

    patient = Patient.query.filter_by(uhid=uhid).first_or_404()
    assessment = Assessment.query.filter_by(uhid=uhid, visit_date=visiting_date).first()
    
    if request.method == 'POST':
        # Retrieve all form data and store in JSON fields
        # Add new Review and Referral fields (These are outside the JSON blocks)
        review_patient = request.form.get('review_patient')
        review_patient_details = request.form.get('review_patient_details')
        referral = request.form.get('referral')
        referral_details = request.form.get('referral_details')

        demographics = {
            'address': request.form.get('address'),
            'marital_status': request.form.get('marital_status'),
            'religion': request.form.get('religion'),
            'occupation': request.form.get('occupation'),
            'education': request.form.get('education')
        }

        # 1. Get the list of complaints from the dropdown
        complaints_list = request.form.getlist('chief_complaints')
# 2. Get the custom text from the textarea
        custom_complaint = request.form.get('other_complaint_details', '').strip()

# 3. If custom text exists AND 'Other' was selected, append the custom text.
# If 'Other' wasn't selected, you might still want to append the custom text if a user typed in the box and missed the dropdown.
        if custom_complaint:
    # Optional: If you want to replace 'Other' with the custom text, you'd do extra logic here.
    # But the simplest way is to append it to the list.
           complaints_list.append(custom_complaint)
        
        chief_complaints = {
            'complaints': complaints_list,
            'duration': request.form.get('duration'),
            'mode_of_onset': request.form.get('mode_of_onset'),
            'course': request.form.get('course'),
            'precipitating_factors': request.form.get('precipitating_factors')
        }
        
        history = {
            'history_present_illness': request.form.get('history_present_illness'),
            'negative_history': request.form.get('negative_history'),
            'medical_history': request.form.get('medical_history'),
            'family_history': request.form.get('family_history')
        }

        personal_history = {
            'birth_and_development': request.form.get('birth_and_development'),
            'mother_antenatal_period': request.form.get('mother_antenatal_period'),
            'birth_history': request.form.get('birth_history'),
            'birth_weight': request.form.get('birth_weight'),
            'developmental_milestones': request.form.get('developmental_milestones'),
            'childhood_history': request.form.get('childhood_history'),
            'education_occupation': request.form.get('education_occupation'),
            'sexual_history': request.form.get('sexual_history'),
            'sexual_orientation': request.form.get('sexual_orientation'),
            'partners': request.form.get('partners'),
            'dysfunction_risk': request.form.get('dysfunction_risk'),
            'menstrual_history': request.form.get('menstrual_history')
        }
        
        premorbid_personality = {
            'social_relations': request.form.get('social_relations'),
            'hobbies_interests': request.form.get('hobbies_interests'),
            'mood': request.form.get('mood'),
            'attitude_work': request.form.get('attitude_work'),
            'morals': request.form.get('morals'),
            'religious': request.form.get('religious'),
            'health_standards': request.form.get('health_standards'),
            'prominent_traits': request.form.get('prominent_traits')
        }

        physical_exam = {
            'pulse': request.form.get('pulse'),
            'bp': request.form.get('bp'), # Note: A top-level BP is also captured
            'anaemia': f"{request.form.get('anaemia')}: {request.form.get('anaemia_details')}" if request.form.get('anaemia') else None,
            'jaundice': f"{request.form.get('jaundice')}: {request.form.get('jaundice_details')}" if request.form.get('jaundice') else None,
            'goitre': f"{request.form.get('goitre')}: {request.form.get('goitre_details')}" if request.form.get('goitre') else None,
            'lymphadenopathy': f"{request.form.get('lymphadenopathy')}: {request.form.get('lymphadenopathy_details')}" if request.form.get('lymphadenopathy') else None,
            'cvs': request.form.get('cvs'),
            'rs': request.form.get('rs'),
            'abd': request.form.get('abd'),
            'cns': request.form.get('cns'),
            'thyroid': request.form.get('thyroid')
        }
        
        mental_status = {
            'general_appearance': request.form.get('general_appearance'),
            'psychomotor_activity': request.form.get('psychomotor_activity'),
            'mood': request.form.get('mood'),
            'affect': request.form.get('affect'),
            'speech': request.form.get('speech')
        }
        
        cognitive_functions = {
            'attention_concentration': request.form.get('attention_concentration'),
            'orientation': request.form.get('orientation'),
            'memory': request.form.get('memory'),
            'arithmetic_ability': request.form.get('arithmetic_ability'),
            'abstraction': request.form.get('abstraction'),
            'judgement': request.form.get('judgement'),
            'insight': request.form.get('insight')
        }
        
        
        previous_history = {
            'previous_diagnosis': request.form.get('previous_diagnosis_radio') + ': ' + (request.form.get('previous_diagnosis') if request.form.get('previous_diagnosis_radio') == 'yes' else 'N/A'),
            'adverse_effects': request.form.get('adverse_effects'),
            'previous_medications': request.form.get('previous_medications')
        }
        
        scales = {
            'BDI': f"{request.form.get('scale_bdi')}: {request.form.get('bdi_score')}" if request.form.get('scale_bdi') == 'yes' else 'N/A',
            'Hamilton Anxiety Scale': f"{request.form.get('scale_hamilton')}: {request.form.get('hamilton_score')}" if request.form.get('scale_hamilton') == 'yes' else 'N/A',
            'Brief Psychiatric Rating Scale': f"{request.form.get('scale_bprs')}: {request.form.get('bprs_score')}" if request.form.get('scale_bprs') == 'yes' else 'N/A',
            'Positive and Negative Syndrome Scale': f"{request.form.get('scale_panss')}: {request.form.get('panss_score')}" if request.form.get('scale_panss') == 'yes' else 'N/A',
            'Global Assessment of Functioning Scale': f"{request.form.get('scale_gaf')}: {request.form.get('gaf_score')}" if request.form.get('scale_gaf') == 'yes' else 'N/A',
            'Montgomery-Asberg Depression Rating Scale': f"{request.form.get('scale_madrs')}: {request.form.get('madrs_score')}" if request.form.get('scale_madrs') == 'yes' else 'N/A',
            'Beck Anxiety Inventory': f"{request.form.get('scale_bai')}: {request.form.get('bai_score')}" if request.form.get('scale_bai') == 'yes' else 'N/A',
            'Depression Anxiety Stress Scales': f"{request.form.get('scale_dass')}: {request.form.get('dass_score')}" if request.form.get('scale_dass') == 'yes' else 'N/A',
            'Brief Negative Symptoms Scale': f"{request.form.get('scale_bnss')}: {request.form.get('bnss_score')}" if request.form.get('scale_bnss') == 'yes' else 'N/A',
            'Mclean Screening Instrument for BPD': f"{request.form.get('scale_msi')}: {request.form.get('msi_score')}" if request.form.get('scale_msi') == 'yes' else 'N/A',
            'Zanarini Rating Scale for BPD': f"{request.form.get('scale_zrs')}: {request.form.get('zrs_score')}" if request.form.get('scale_zrs') == 'yes' else 'N/A'
        }

        # Check if an assessment already exists and update, otherwise add new one
        if assessment:
            assessment.demographics = demographics
            assessment.chief_complaints = chief_complaints
            assessment.history = history
            assessment.personal_history = personal_history
            assessment.premorbid_personality = premorbid_personality
            assessment.physical_exam = physical_exam
            assessment.mental_status = mental_status
            assessment.cognitive_functions = cognitive_functions
            assessment.previous_history = previous_history
            assessment.scales = scales
            
            # Add new Review and Referral fields to existing assessment object
            assessment.review_patient = review_patient
            assessment.review_patient_details = review_patient_details
            assessment.referral = referral
            assessment.referral_details = referral_details
        else:
            assessment_data = Assessment(uhid=patient.uhid, visit_date=visiting_date) # Add the visiting_date here
            assessment_data.demographics = demographics
            assessment_data.chief_complaints = chief_complaints
            assessment_data.history = history
            assessment_data.personal_history = personal_history
            assessment_data.premorbid_personality = premorbid_personality
            assessment_data.physical_exam = physical_exam
            assessment_data.mental_status = mental_status
            assessment_data.cognitive_functions = cognitive_functions
            assessment_data.previous_history = previous_history
            assessment_data.scales = scales
            
            # Add new Review and Referral fields to new assessment object
            assessment_data.review_patient = review_patient
            assessment_data.review_patient_details = review_patient_details
            assessment_data.referral = referral
            assessment_data.referral_details = referral_details
            
            db.session.add(assessment_data)

        db.session.commit()
        
        flash('Assessment saved successfully!', 'success')
        # Redirect to the treatment form after saving assessment
        return redirect(url_for('treatment_form', uhid=uhid, visiting_date=visiting_date_str))
    
    # Get the username and user_role from the session
    username = session.get('username')
    user_role = session.get('user_role')
    
    return render_template('assessment.html', patient=patient, assessment=assessment, username=username, user_role=user_role,visiting_date=visiting_date)



@app.route('/treatment/<uhid>', methods=['GET', 'POST'])
def treatment_form(uhid):
    if 'username' not in session:
        return redirect(url_for('login'))
    
    patient = Patient.query.filter_by(uhid=uhid).first_or_404()
    visiting_date_str = request.args.get('visiting_date')
    visiting_date = datetime.strptime(visiting_date_str, '%Y-%m-%d').date() if visiting_date_str else date.today()
    
    if request.method == 'POST':
        try:
            primary_diagnosis = request.form.get('diagnosis_description')
            if primary_diagnosis == 'Other':
                primary_diagnosis = request.form.get('diagnosis_description_other')

            secondary_diagnosis = request.form.get('secondary_diagnosis')
            if secondary_diagnosis == 'Other':
                secondary_diagnosis = request.form.get('secondary_diagnosis_other')
            
            psychotherapy_plan = request.form.get('psychotherapy_plan')
            if psychotherapy_plan == 'Other':
                psychotherapy_plan = request.form.get('psychotherapy_plan_other')
            
            diagnosis_data = {
                'primary_diagnosis': primary_diagnosis,
                'secondary_diagnosis': secondary_diagnosis
            }
            psychotherapy_data = {
                'psychotherapy_plan': psychotherapy_plan
            }
            
            medications_data = []
            med_names = request.form.getlist('medication_name[]')
            med_name_others = request.form.getlist('medication_name_other[]')
            med_dosages = request.form.getlist('dosage[]')
            med_dosage_others = request.form.getlist('dosage_other[]')
            med_frequencies = request.form.getlist('frequency[]')
            med_frequency_others = request.form.getlist('frequency_other[]')
            med_instructions = request.form.getlist('instruction[]')
            med_instruction_others = request.form.getlist('instruction_other[]')

            for i in range(len(med_names)):
                name = med_name_others[i] if med_names[i] == 'Other' else med_names[i]
                dosage = med_dosage_others[i] if med_dosages[i] == 'Other' else med_dosages[i]
                frequency = med_frequency_others[i] if med_frequencies[i] == 'Other' else med_frequencies[i]
                instruction = med_instruction_others[i] if med_instructions[i] == 'Other' else med_instructions[i]

                medication = {
                    'name': name,
                    'dosage': dosage,
                    'frequency': frequency,
                    'instruction': instruction
                }
                medications_data.append(medication)

            existing_treatment = Treatment.query.filter_by(uhid=uhid, visit_date=visiting_date).first()
            if existing_treatment:
                existing_treatment.diagnosis = diagnosis_data
                existing_treatment.psychotherapy = psychotherapy_data
                existing_treatment.medications = medications_data
            else:
                new_treatment = Treatment(
                    uhid=uhid,
                    diagnosis=diagnosis_data,
                    psychotherapy=psychotherapy_data,
                    medications=medications_data
                )
                db.session.add(new_treatment)
            
            db.session.commit()
            
            return jsonify({'message': 'Successfully saved data!'}), 200
        
        except Exception as e:
            db.session.rollback()
            return jsonify({'message': f'Failed to save data. Please try again. Error: {str(e)}'}), 500

    treatment = Treatment.query.filter_by(uhid=uhid, visit_date=visiting_date).order_by(Treatment.created_at.desc()).first()
    username = session.get('username')
    user_role = session.get('user_role')
    return render_template('treatment.html', patient=patient, treatment=treatment, username=username, user_role=user_role, visiting_date=visiting_date)


# In your venkat.py file, locate and replace the existing function
# with the following corrected version.
ist = pytz.timezone('Asia/Kolkata')

@app.route('/prescription_history/<uhid>')
def prescription_history(uhid):
    if 'username' not in session:
        return redirect(url_for('login'))
    
    patient = Patient.query.filter_by(uhid=uhid).first_or_404()

    # Fetch all data from the database
    prescriptions = Treatment.query.filter_by(uhid=uhid).order_by(Treatment.created_at.desc()).all()
    lab_reports = LabReport.query.filter_by(uhid=uhid).order_by(LabReport.created_at.desc()).all()
    assessments = Assessment.query.filter_by(uhid=uhid).order_by(Assessment.created_at.desc()).all()

    # Convert ALL timestamps to IST before doing any other operations
    for item in prescriptions + lab_reports + assessments:
        if item.created_at and item.created_at.tzinfo is None:
            item.created_at = pytz.utc.localize(item.created_at)
        if item.created_at:
            item.created_at = item.created_at.astimezone(ist)

    # Now, create the dictionaries with the correctly converted dates
    lab_report_dict = {lr.created_at.date(): lr for lr in lab_reports}
    assessment_dict = {a.created_at.date(): a for a in assessments}

    # Attach the corresponding lab report + assessment to each prescription
    for prescription in prescriptions:
        visit_date = prescription.created_at.date()
        prescription.lab_report = lab_report_dict.get(visit_date)
        prescription.assessment = assessment_dict.get(visit_date)

    latest_assessment = assessments[0] if assessments else None
    visiting_date_str = request.args.get('visiting_date')
    visiting_date = datetime.strptime(visiting_date_str, '%Y-%m-%d').date() if visiting_date_str else date.today()

    username = session.get('username') 
    user_role = session.get('user_role') 
    
    return render_template(
        'prescription_history.html',
        patient=patient,
        prescriptions=prescriptions,
        latest_assessment=latest_assessment,
        visiting_date=visiting_date, 
        username=username,
        user_role=user_role
    )


# Add this new route to your app.py file
@app.route('/lab_reports/<uhid>', methods=['GET', 'POST'])
def lab_reports_form(uhid):
    # Check if the user is logged in
    if 'username' not in session:
        return redirect(url_for('login'))
    patient = Patient.query.filter_by(uhid=uhid).first_or_404()
    lab_report = LabReport.query.filter_by(uhid=uhid).first()
    visiting_date_str = request.args.get('visiting_date')
    visiting_date = datetime.strptime(visiting_date_str, '%Y-%m-%d').date() if visiting_date_str else date.today()

    if request.method == 'POST':
        try:
            # Retrieve the new summary fields
            test_summary = request.form.get('test_summary', '')
            scan_summary = request.form.get('scan_summary', '')
            
            # Process dynamic test fields and include the summary
            tests_data = {'summary': test_summary, 'details': []}
            test_count = 1
            while True:
                test_name = request.form.get(f'test_name_{test_count}')
                test_value = request.form.get(f'test_value_{test_count}')
                if test_name is None:
                    break
                if test_name and test_value:
                    tests_data['details'].append({'name': test_name, 'value': test_value})
                test_count += 1
            
            # Process scans data and include the summary
            scan_name = request.form.get('scans_prescribed')
            if scan_name == 'Other':
                scan_name = request.form.get('scans_prescribed_other')
            
            scans_data = {
                'name': scan_name, 
                'summary': scan_summary,
                'tests_file': '',
                'scans_file': ''
            }
            
            tests_file = request.files.get('tests_file')
            if tests_file and tests_file.filename != '':
                filename = secure_filename(tests_file.filename)
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                tests_file.save(file_path) # Save the file to the server
                scans_data['tests_file'] = filename # Store only the filename in the database

            scans_file = request.files.get('scans_file')
            if scans_file and scans_file.filename != '':
                filename = secure_filename(scans_file.filename)
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                scans_file.save(file_path) # Save the file to the server
                scans_data['scans_file'] = filename # Store only the filename in the database
            lab_report = LabReport.query.filter_by(uhid=uhid, visit_date=visiting_date).first()
            if lab_report:
                lab_report.tests = tests_data
                lab_report.scans = scans_data
            else:
                new_lab_report = LabReport(
                    uhid=uhid,
                    visit_date=visiting_date,
                    tests=tests_data,
                    scans=scans_data
                )
                db.session.add(new_lab_report)

            db.session.commit()
            flash('Lab reports and scans saved successfully!', 'success')
            return redirect(url_for('prescription_summary', uhid=uhid, visiting_date=visiting_date_str))
        
        except Exception as e:
            db.session.rollback()
            flash(f'Failed to save lab reports. Please try again. Error: {str(e)}', 'danger')
            return redirect(url_for('lab_reports_form', uhid=uhid, visiting_date=visiting_date_str))
        
    lab_report = LabReport.query.filter_by(uhid=uhid, visit_date=visiting_date).first()        
    username = session.get('username')
    user_role = session.get('user_role')

    return render_template('lab_reports.html', patient=patient, lab_report=lab_report, username=username, user_role=user_role, visiting_date=visiting_date)

@app.route('/prescription/<string:uhid>/summary')
def prescription_summary(uhid):
    patient = Patient.query.filter_by(uhid=uhid).first_or_404()
    # Get the latest records for the patient
    assessment = Assessment.query.filter_by(uhid=uhid).order_by(Assessment.created_at.desc()).first()
    treatment = Treatment.query.filter_by(uhid=uhid).order_by(Treatment.created_at.desc()).first()
    lab_report = LabReport.query.filter_by(uhid=uhid).order_by(LabReport.created_at.desc()).first()

    # Pass the data directly to the template
    return render_template(
        'prescription.html',
        patient=patient,
        assessment=assessment,
        treatment=treatment,
        lab_report=lab_report,
        visiting_date=date.today()
    )


@app.route('/save_prescription/<uhid>', methods=['POST'])
def save_prescription(uhid):
    if 'username' not in session:
        return redirect(url_for('login'))

    visiting_date_str = request.form.get('visiting_date')
    visiting_date = datetime.strptime(visiting_date_str, '%Y-%m-%d').date()

    # Fetch patient + related records
    patient = Patient.query.filter_by(uhid=uhid).first_or_404()
    assessment = Assessment.query.filter_by(uhid=uhid, visit_date=visiting_date).first()
    treatment = Treatment.query.filter_by(uhid=uhid, visit_date=visiting_date).first()
    lab_report = LabReport.query.filter_by(uhid=uhid, visit_date=visiting_date).first()

    try:
        # If treatment exists, we assume it's already saved
        if not treatment:
            new_treatment = Treatment(
                uhid=uhid,
                visit_date=visiting_date,
                diagnosis=assessment.chief_complaints if assessment else {},
                psychotherapy={'psychotherapy_plan': 'N/A'},
                medications=[]
            )
            db.session.add(new_treatment)

        db.session.commit()
        flash("Prescription saved successfully!", "success")

    except Exception as e:
        db.session.rollback()
        flash(f"Failed to save prescription: {str(e)}", "danger")

    return redirect(url_for('prescription_history', uhid=uhid))



import os
from flask import Flask, session, redirect, url_for, render_template
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np # Import numpy for color calculation

# Assuming you have Flask, SQLAlchemy models (Patient, Treatment), and other necessary imports defined above

import os
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from flask import Flask, render_template, request, redirect, url_for, flash, make_response, send_from_directory, Blueprint
from flask import session

# Assuming Patient, Treatment, url_for, and redirect are defined elsewhere in the application scope

@app.route('/analytics', methods=['GET'])
def analytics():
    # Ensure you have 'import pandas as pd', 'import matplotlib.pyplot as plt', 'import numpy as np' and 'import os' at the top of your main script.
    
    # --- SESSION CHECK AND PATIENT DATA FETCHING ---
    if 'username' not in session:
        return redirect(url_for('login'))
        
    # Fetch all patients
    patients = Patient.query.all()
    total_patients = len(patients)

    # Data for Age Distribution
    age_groups = {'0-18': 0, '19-40': 0, '41-60': 0, '60+': 0}
    for patient in patients:
        # Check if age attribute exists and is valid before comparison
        if hasattr(patient, 'age') and isinstance(patient.age, (int, float)):
            if patient.age <= 18:
                age_groups['0-18'] += 1
            elif 19 <= patient.age <= 40:
                age_groups['19-40'] += 1
            elif 41 <= patient.age <= 60:
                age_groups['41-60'] += 1
            else:
                age_groups['60+'] += 1

    # Data for Abnormal Vitals
    abnormal_vitals = {'bp': 0, 'sugar': 0, 'temp': 0}
    for patient in patients:
        # Ensure boolean checks use hasattr to avoid errors if attributes are missing
        if hasattr(patient, 'abnormal_bp') and patient.abnormal_bp:
            abnormal_vitals['bp'] += 1
        if hasattr(patient, 'abnormal_sugar') and patient.abnormal_sugar:
            abnormal_vitals['sugar'] += 1
        if hasattr(patient, 'abnormal_temp') and patient.abnormal_temp:
            abnormal_vitals['temp'] += 1

    # Data for Monthly Visits
    monthly_visits = {}
    for patient in patients:
        if patient.registration_date:
            # Assuming registration_date is a datetime object
            month_year = patient.registration_date.strftime('%Y-%m')
            if month_year in monthly_visits:
                monthly_visits[month_year] += 1
            else:
                monthly_visits[month_year] = 1

    # Sort monthly data by date
    sorted_months = sorted(monthly_visits.keys())
    monthly_trend_data = {
        'labels': sorted_months,
        'data': [monthly_visits[month] for month in sorted_months]
    }

    # Data for Daily Visits (new plot)
    daily_visits = {}
    for patient in patients:
        if patient.registration_date:
            # Assuming registration_date is a datetime object
            date_str = patient.registration_date.strftime('%Y-%m-%d')
            if date_str in daily_visits:
                daily_visits[date_str] += 1
            else:
                daily_visits[date_str] = 1
    
    # Sort daily data by date
    sorted_dates = sorted(daily_visits.keys())
    daily_trend_data = {
        'labels': sorted_dates,
        'data': [daily_visits[date] for date in sorted_dates]
    }
    
    # Define a consistent directory for saving charts
    save_dir = 'static' # Assuming charts are saved in the 'static' folder
    
    # Plot 1: Age Distribution
    df_age = pd.DataFrame({
        'Age Group': age_groups.keys(),
        'Count': age_groups.values()
    })
    plt.figure(figsize=(8, 8))
    colors = ['#4c9ad6', '#66bb6a', '#ff9800', '#7b1fa2'] 
    plt.pie(
        df_age['Count'], 
        autopct='%1.1f%%', 
        startangle=140, 
        shadow=True,
        colors=colors 
    )
    plt.title('Patient Age Distribution', fontsize=16)
    plt.axis('equal') 
    plt.legend(df_age['Age Group'], loc='lower center', bbox_to_anchor=(0.5, -0.1), ncol=2, title='Age Groups') 
    plt.tight_layout(pad=3.0)
    age_chart_filename = 'age_distribution_chart.png'
    plt.savefig(os.path.join(save_dir, age_chart_filename))
    plt.close()

    # Plot 2: Abnormal Vitals
    df_vitals = pd.DataFrame(abnormal_vitals.items(), columns=['Vitals', 'Count'])
    plt.figure(figsize=(8, 6))
    plt.bar(df_vitals['Vitals'], df_vitals['Count'], color=['red', 'orange', 'blue'])
    plt.title('Abnormal Vitals Count', fontsize=16)
    plt.xlabel('Vitals', fontsize=12)
    plt.ylabel('Count', fontsize=12)
    plt.grid(axis='y', linestyle='--', alpha=0.7)
    plt.tight_layout()
    vitals_chart_filename = 'abnormal_vitals_chart.png'
    plt.savefig(os.path.join(save_dir, vitals_chart_filename))
    plt.close()

    # Plot 3: Monthly Visit Trend
    df_monthly = pd.DataFrame({
      'Month': monthly_trend_data['labels'],
      'Visits': monthly_trend_data['data']
    })
    plt.figure(figsize=(10, 6))
    plt.plot(df_monthly['Month'], df_monthly['Visits'], marker='o', linestyle='-', color='b')
    plt.title('Monthly Visit Trend', fontsize=16)
    plt.xlabel('Month', fontsize=12)
    plt.ylabel('Number of Visits', fontsize=12)
    plt.xticks(rotation=45)
    plt.grid(axis='both', linestyle='--', alpha=0.7)
    plt.tight_layout()
    monthly_chart_filename = 'monthly_visit_trend_line_chart.png'
    plt.savefig(os.path.join(save_dir, monthly_chart_filename))
    plt.close()
    
    # Plot 4: Daily Visit Trend (new)
    df_daily = pd.DataFrame({
        'Date': daily_trend_data['labels'],
        'Visits': daily_trend_data['data']
    })
    plt.figure(figsize=(12, 7))
    plt.plot(df_daily['Date'], df_daily['Visits'], marker='o', linestyle='-', color='purple', linewidth=2)
    plt.title('Daily Patient Visit Trend', fontsize=18)
    plt.xlabel('Date', fontsize=14)
    plt.ylabel('Number of Patients', fontsize=14)
    plt.xticks(rotation=45, ha='right')
    plt.grid(axis='both', linestyle='--', alpha=0.7)
    plt.tight_layout()
    daily_chart_filename = 'daily_visit_trend_line_chart.png'
    plt.savefig(os.path.join(save_dir, daily_chart_filename))
    plt.close()
    
    # --- DATA PREPARATION FOR TRENDS (Diagnosis and Medications) ---
    
    # Fetch all treatment records
    treatments = Treatment.query.all()
    
    # Prepare data for trends DataFrame
    data_for_df = []
    for t in treatments:
        # Extract date as YYYY-MM
        month_year = t.visit_date.strftime('%Y-%m') if hasattr(t, 'visit_date') and t.visit_date else 'Unknown'
        
        # --- REVISED DATA EXTRACTION FOR DIAGNOSIS (TO MATCH TREATMENT ROUTE) ---
        primary_diag_name = None
        secondary_diag_name = None
        
        if hasattr(t, 'diagnosis') and t.diagnosis and isinstance(t.diagnosis, dict):
            # Primary Diagnosis 
            primary_diag = t.diagnosis.get('primary_diagnosis')
            if primary_diag and primary_diag.strip():
                primary_diag_name = primary_diag.strip()

            # Secondary Diagnosis
            secondary_diag = t.diagnosis.get('secondary_diagnosis')
            if secondary_diag and secondary_diag.strip():
                secondary_diag_name = secondary_diag.strip()
        # --- END REVISED DATA EXTRACTION ---
        
        # Extract Medications
        medication_names = []
        if hasattr(t, 'medications') and t.medications and isinstance(t.medications, list):
            for m in t.medications:
                if isinstance(m, dict) and 'name' in m:
                    medication_names.append(m['name'])
        
        data_for_df.append({
            'date_month': month_year,
            'primary_diagnosis': primary_diag_name, 
            'secondary_diagnosis': secondary_diag_name,
            'medications': medication_names
        })

    df_trends = pd.DataFrame(data_for_df)

    
    # --- DIAGNOSIS DATA MELTING (for Primary and Secondary separation) ---
    df_diagnosis_melted = pd.DataFrame()
    if not df_trends.empty:
        # Melt the DataFrame to long format for easy counting and plotting
        df_diagnosis_melted = pd.melt(
            df_trends.rename(columns={'primary_diagnosis': 'Primary', 'secondary_diagnosis': 'Secondary'}),
            id_vars=['date_month'],
            value_vars=['Primary', 'Secondary'],
            var_name='diagnosis_type',
            value_name='diagnosis_name'
        )
        
        # Filter out empty/None diagnosis names
        df_diagnosis_melted = df_diagnosis_melted[df_diagnosis_melted['diagnosis_name'].astype(str).str.strip() != ''].copy()
        df_diagnosis_melted.dropna(subset=['diagnosis_name'], inplace=True)


    # --- START: Plot 5: Primary Diagnosis Trend (PERCENTAGE STACKED BAR CHART) ---
    primary_diagnosis_chart_filename = 'primary_diagnosis_trend_pct_stacked_bar_chart.png'

    # 1. Filter for Primary Diagnosis only
    df_primary = df_diagnosis_melted[df_diagnosis_melted['diagnosis_type'] == 'Primary'].copy()

    if not df_primary.empty:
        # 2. Group by month and diagnosis name to get counts
        primary_counts = df_primary.groupby(['date_month', 'diagnosis_name']).size().reset_index(name='Count')
        
        # 3. Pivot the data to wide format required for plotting
        df_primary_pivot = primary_counts.pivot(index='date_month', columns='diagnosis_name', values='Count').fillna(0)
        
        # Ensure all months are represented and sorted
        all_months_primary = sorted(df_primary_pivot.index.unique())
        df_primary_pivot = df_primary_pivot.reindex(all_months_primary, fill_value=0)
        
        # ******* Calculate Percentage *******
        # Calculate the total count for each month
        df_primary_pivot['MonthlyTotal'] = df_primary_pivot.sum(axis=1)
        # Calculate percentage
        # Check for division by zero (if a month has 0 treatments)
        df_primary_pct = df_primary_pivot.iloc[:, :-1].div(df_primary_pivot['MonthlyTotal'].replace(0, 1), axis=0) * 100
        
        # Data for plotting
        categories_primary = df_primary_pct.columns
        months_primary = df_primary_pct.index
        
        # 4. Define Color Mapping (Using the tab20 categorical colormap for bright, distinct colors)
        num_primary_diag = len(categories_primary)
        plot_colors_primary = [plt.cm.get_cmap('tab20')(i % 20) for i in range(num_primary_diag)]
        
        plt.figure(figsize=(14, 8))
        
        # ******* Generate the Percentage Stacked Bar Chart *******
        bottom_val = np.zeros(len(months_primary))
        bar_width = 0.8 # Width of the bars
        
        for i, category in enumerate(categories_primary):
            values = df_primary_pct[category].values
            plt.bar(
                months_primary,
                values,
                bottom=bottom_val,
                label=category,
                color=plot_colors_primary[i],
                width=bar_width,
                edgecolor='white'
            )
            
            # *** UPDATED: Add percentage labels to the stacked bars ***
            for j, val in enumerate(values):
                # Only label if the percentage is significant enough (e.g., > 1.0%)
                if val >= 1.0: 
                    # Calculate position: x is the index of the month, y is the center of the segment
                    x_pos = j
                    y_pos = bottom_val[j] + val / 2
                    
                    # Ensure label is not placed on top of 100% line
                    if y_pos < 99.5 and val > 0:
                        plt.text(
                            x_pos, y_pos,
                            f'{val:.1f}%', # Format to one decimal place
                            ha='center', va='center',
                            fontsize=8,
                            color='black', # Black text for contrast
                            fontweight='bold'
                        )
            
            # Update bottom for the next stack
            bottom_val += values

        # Add 100% line for reference
        plt.axhline(100, color='gray', linestyle='--', linewidth=1)
        
        plt.xticks(rotation=45, ha='right') 
        
        # Place the legend outside the plot
        plt.legend(title='Primary Diagnosis', bbox_to_anchor=(1.05, 1), loc='upper left', fontsize='small')
        
        plt.title('Monthly Trend of Primary Diagnoses (Percentage Stacked Bar)', fontsize=16) 
        plt.xlabel('Month', fontsize=12)
        plt.ylabel('Percentage of Monthly Primary Cases (%)', fontsize=12) 
        plt.ylim(0, 100) # Ensure y-axis is 0-100
        plt.grid(axis='y', linestyle='--', alpha=0.7)
        plt.tight_layout(rect=[0, 0, 0.80, 1]) # Adjust space for the legend
    else:
        # Placeholder for no valid diagnosis data
        plt.figure(figsize=(12, 8)) 
        plt.text(0.5, 0.5, 'No valid Primary Diagnosis trend data available.', ha='center', va='center', fontsize=12)
        plt.title('Monthly Trend of Primary Diagnoses (Percentage Stacked Bar)') 
        plt.xticks([])
        plt.yticks([])
        plt.tight_layout()
            
    plt.savefig(os.path.join(save_dir, primary_diagnosis_chart_filename))
    plt.close()
    # --- END: Plot 5: Primary Diagnosis Trend (PERCENTAGE STACKED BAR CHART) ---

    # --- START: NEW Plot 6: Secondary Diagnosis Trend (PERCENTAGE STACKED BAR CHART) ---
    secondary_diagnosis_chart_filename = 'secondary_diagnosis_trend_pct_stacked_bar_chart.png'

    # 1. Filter for Secondary Diagnosis only
    df_secondary = df_diagnosis_melted[df_diagnosis_melted['diagnosis_type'] == 'Secondary'].copy()

    if not df_secondary.empty:
        # 2. Group by month and diagnosis name to get counts
        secondary_counts = df_secondary.groupby(['date_month', 'diagnosis_name']).size().reset_index(name='Count')
        
        # 3. Pivot the data to wide format required for plotting
        df_secondary_pivot = secondary_counts.pivot(index='date_month', columns='diagnosis_name', values='Count').fillna(0)
        
        # Ensure all months are represented and sorted
        all_months_secondary = sorted(df_secondary_pivot.index.unique())
        df_secondary_pivot = df_secondary_pivot.reindex(all_months_secondary, fill_value=0)
        
        # ******* Calculate Percentage *******
        # Calculate the total count for each month
        df_secondary_pivot['MonthlyTotal'] = df_secondary_pivot.sum(axis=1)
        # Calculate percentage
        # Check for division by zero (if a month has 0 treatments)
        df_secondary_pct = df_secondary_pivot.iloc[:, :-1].div(df_secondary_pivot['MonthlyTotal'].replace(0, 1), axis=0) * 100
        
        # Data for plotting
        categories_secondary = df_secondary_pct.columns
        months_secondary = df_secondary_pct.index
        
        # 4. Define Color Mapping (Using the tab20b categorical colormap for bright, distinct colors)
        num_secondary_diag = len(categories_secondary)
        plot_colors_secondary = [plt.cm.get_cmap('tab20b')(i % 20) for i in range(num_secondary_diag)] 
        
        plt.figure(figsize=(14, 8))
        
        # ******* Generate the Percentage Stacked Bar Chart *******
        bottom_val = np.zeros(len(months_secondary))
        bar_width = 0.8 # Width of the bars
        
        for i, category in enumerate(categories_secondary):
            values = df_secondary_pct[category].values
            plt.bar(
                months_secondary,
                values,
                bottom=bottom_val,
                label=category,
                color=plot_colors_secondary[i],
                width=bar_width,
                edgecolor='white'
            )
            
            # *** UPDATED: Add percentage labels to the stacked bars ***
            for j, val in enumerate(values):
                # Only label if the percentage is significant enough (e.g., > 1.0%)
                if val >= 1.0: 
                    # Calculate position: x is the index of the month, y is the center of the segment
                    x_pos = j
                    y_pos = bottom_val[j] + val / 2
                    
                    # Ensure label is not placed on top of 100% line
                    if y_pos < 99.5 and val > 0:
                        plt.text(
                            x_pos, y_pos,
                            f'{val:.1f}%', # Format to one decimal place
                            ha='center', va='center',
                            fontsize=8,
                            color='black', # Black text for contrast
                            fontweight='bold'
                        )
            
            # Update bottom for the next stack
            bottom_val += values

        # Add 100% line for reference
        plt.axhline(100, color='gray', linestyle='--', linewidth=1)
        
        plt.xticks(rotation=45, ha='right') 
        
        # Place the legend outside the plot
        plt.legend(title='Secondary Diagnosis', bbox_to_anchor=(1.05, 1), loc='upper left', fontsize='small')
        
        plt.title('Monthly Trend of Secondary Diagnoses (Percentage Stacked Bar)', fontsize=16) 
        plt.xlabel('Month', fontsize=12)
        plt.ylabel('Percentage of Monthly Secondary Cases (%)', fontsize=12) 
        plt.ylim(0, 100) # Ensure y-axis is 0-100
        plt.grid(axis='y', linestyle='--', alpha=0.7)
        plt.tight_layout(rect=[0, 0, 0.80, 1]) # Adjust space for the legend
    else:
        # Placeholder for no valid diagnosis data
        plt.figure(figsize=(12, 8)) 
        plt.text(0.5, 0.5, 'No valid Secondary Diagnosis trend data available.', ha='center', va='center', fontsize=12)
        plt.title('Monthly Trend of Secondary Diagnoses (Percentage Stacked Bar)') 
        plt.xticks([])
        plt.yticks([])
        plt.tight_layout()
            
    plt.savefig(os.path.join(save_dir, secondary_diagnosis_chart_filename))
    plt.close()
    # --- END: NEW Plot 6: Secondary Diagnosis Trend (PERCENTAGE STACKED BAR CHART) ---


    # --- START: Plot 7 (OLD Plot 6): Medication Trend (HORIZONTAL BAR CHART - ALL NOTED) ---
    medication_chart_filename = 'all_noted_medications_hbar_chart.png'
        
    # df_meds_exploded prepares the data for counting overall prescriptions
    df_meds_exploded = df_trends.explode('medications').rename(columns={'medications': 'medication_name'})
    # Filter out empty/None medication names
    df_meds_exploded = df_meds_exploded[df_meds_exploded['medication_name'].astype(str).str.strip() != '']

    if not df_meds_exploded.empty:
        # Get overall counts for ALL noted medications (NO filter)
        medication_counts = df_meds_exploded['medication_name'].value_counts()
        df_all_meds = medication_counts.reset_index()
        
        # Ensure 'Medication' column is correctly named 
        if df_all_meds.shape[1] == 2:
            df_all_meds.columns = ['Medication', 'Count']
        
        plt.figure(figsize=(10, len(df_all_meds) * 0.75 + 1)) # Dynamic height for readability
            
        if not df_all_meds.empty:
            # Sort for clean visualization (highest count on top)
            df_all_meds = df_all_meds.sort_values(by='Count', ascending=True)
            plt.barh(df_all_meds['Medication'], df_all_meds['Count'], color="#00b60f")
                
            plt.title('All Noted Prescribed Medications/Treatments (Overall)', fontsize=16) # Updated title
            plt.xlabel('Number of Prescriptions', fontsize=12)
            plt.ylabel('Medication/Treatment', fontsize=12)
            plt.grid(axis='x', linestyle='--', alpha=0.7)
                
            # Add labels to the bars
            for index, value in enumerate(df_all_meds['Count']):
                plt.text(value, index, f' {int(value)}', va='center')
                    
        else:
            plt.text(0.5, 0.5, 'No medication/treatment data available.', ha='center', va='center', fontsize=12)
            plt.title('All Noted Prescribed Medications/Treatments')
            plt.xticks([])
            plt.yticks([])
            
        plt.tight_layout()
        plt.savefig(os.path.join(save_dir, medication_chart_filename))
        plt.close()
    else:
        # Create a placeholder if no data is available
        plt.figure(figsize=(10, 6))
        plt.text(0.5, 0.5, 'No medication/treatment data available.', ha='center', va='center', fontsize=12)
        plt.title('All Noted Prescribed Medications/Treatments')
        plt.xticks([])
        plt.yticks([])
        plt.tight_layout()
        plt.savefig(os.path.join(save_dir, medication_chart_filename))
        plt.close()
    # --- END: Plot 7: Medication Trend (HORIZONTAL BAR CHART - ALL NOTED) ---
        
    # Get the username and user_role from the session
    username = session.get('username')
    user_role = session.get('user_role')
    
    # Render the HTML template, ensuring all chart URLs are passed
    return render_template(
        'analytics.html', 
        total_patients=total_patients,
        age_chart_url=url_for('static', filename=age_chart_filename),
        vitals_chart_url=url_for('static', filename=vitals_chart_filename),
        monthly_chart_url=url_for('static', filename=monthly_chart_filename),
        daily_chart_url=url_for('static', filename=daily_chart_filename),
        # UPDATED: New URLs for percentage stacked bar charts
        primary_diagnosis_chart_url=url_for('static', filename=primary_diagnosis_chart_filename),
        secondary_diagnosis_chart_url=url_for('static', filename=secondary_diagnosis_chart_filename),
        # Medication chart URL remains
        medication_chart_url=url_for('static', filename=medication_chart_filename),
        username=username, 
        user_role=user_role
    )
    
@app.route('/download_prescription_pdf/<uhid>')
def download_prescription_pdf(uhid):
    if not REPORTLAB_AVAILABLE:
        flash("PDF generation is not available. Please install ReportLab.", 'danger')
        return redirect(url_for('prescription_summary', uhid=uhid))

    patient = Patient.query.filter_by(uhid=uhid).first_or_404()
    assessment = Assessment.query.filter_by(uhid=uhid).first()
    treatment = Treatment.query.filter_by(uhid=uhid).first()
    # Correctly define the lab_report variable
    lab_report = LabReport.query.filter_by(uhid=uhid).first()

    # Create a buffer to hold the PDF
    buffer = BytesIO()

    # Create a new PDF document
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=18)
    story = []

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='TitleStyle', fontSize=24, leading=28, alignment=1, fontName='Helvetica-Bold'))
    
    styles['Heading3'].fontSize = 14
    styles['Heading3'].leading = 16
    styles['Heading3'].fontName = 'Helvetica-Bold'
    
    styles['Normal'].fontSize = 12
    styles['Normal'].leading = 14
    
    styles.add(ParagraphStyle(name='Bold', fontSize=12, leading=14, fontName='Helvetica-Bold'))

    # Add Title
    story.append(Paragraph("Psychiatric Prescription", styles['TitleStyle']))
    story.append(Spacer(1, 12))

    # Patient Details
    story.append(Paragraph("Patient Details", styles['Heading3']))
    story.append(Paragraph(f"<b>Patient ID:</b> {patient.uhid}", styles['Normal']))
    story.append(Paragraph(f"<b>Name:</b> {patient.name}", styles['Normal']))
    story.append(Paragraph(f"<b>Age:</b> {patient.age} | <b>Gender:</b> {patient.gender}", styles['Normal']))
    story.append(Paragraph(f"<b>Mobile:</b> {patient.mobile_no} | <b>Email:</b> {patient.email}", styles['Normal']))
    story.append(Spacer(1, 12))

    if assessment and assessment.demographics:
        story.append(Paragraph("Demographic Details", styles['Heading3']))
        story.append(Paragraph(f"<b>Address:</b> {assessment.demographics.get('address', 'N/A')}", styles['Normal']))
        story.append(Paragraph(f"<b>Marital Status:</b> {assessment.demographics.get('marital_status', 'N/A')}", styles['Normal']))
        story.append(Paragraph(f"<b>Religion:</b> {assessment.demographics.get('religion', 'N/A')}", styles['Normal']))
        story.append(Paragraph(f"<b>Occupation:</b> {assessment.demographics.get('occupation', 'N/A')}", styles['Normal']))
        story.append(Paragraph(f"<b>Education:</b> {assessment.demographics.get('education', 'N/A')}", styles['Normal']))
        story.append(Spacer(1, 12))

    # Assessment Summary
    if assessment:
        story.append(Paragraph("Assessment Summary", styles['Heading3']))
        if assessment.chief_complaints:
            story.append(Paragraph("Chief Complaints", styles['Heading3']))
            chief_complaints = assessment.chief_complaints
            complaints = ', '.join(chief_complaints.get('complaints', []))
            story.append(Paragraph(f"<b>Complaints:</b> {complaints}", styles['Normal']))
            story.append(Paragraph(f"<b>Duration:</b> {chief_complaints.get('duration', 'N/A')}", styles['Normal']))
            story.append(Paragraph(f"<b>Mode of Onset:</b> {chief_complaints.get('mode_of_onset', 'N/A')}", styles['Normal']))
            story.append(Paragraph(f"<b>Course:</b> {chief_complaints.get('course', 'N/A')}", styles['Normal']))
            story.append(Paragraph(f"<b>Precipitating Factors:</b> {chief_complaints.get('precipitating_factors', 'N/A')}", styles['Normal']))
            story.append(Spacer(1, 12))

                # History
        if assessment.history:
            story.append(Paragraph("History", styles['Heading3']))
            history_data = assessment.history
            story.append(Paragraph(f"<b>History of Present Illness:</b> {history_data.get('history_present_illness', 'N/A')}", styles['Normal']))
            story.append(Paragraph(f"<b>Negative History:</b> {history_data.get('negative_history', 'N/A')}", styles['Normal']))
            story.append(Paragraph(f"<b>Medical History:</b> {history_data.get('medical_history', 'N/A')}", styles['Normal']))
            story.append(Paragraph(f"<b>Family History:</b> {history_data.get('family_history', 'N/A')}", styles['Normal']))
            story.append(Spacer(1, 12))

    
        # Previous History
        if assessment.previous_history:
            story.append(Paragraph("Previous History", styles['Heading3']))
            previous_history_data = assessment.previous_history
            story.append(Paragraph(f"<b>Previous Diagnosis:</b> {previous_history_data.get('previous_diagnosis', 'N/A')}", styles['Normal']))
            story.append(Paragraph(f"<b>Previous Medications:</b> {previous_history_data.get('previous_medications', 'N/A')}", styles['Normal']))
            story.append(Paragraph(f"<b>Adverse Effects:</b> {previous_history_data.get('adverse_effects', 'N/A')}", styles['Normal']))
            story.append(Spacer(1, 12))

        # Physical Examination
        if assessment.physical_exam:
            story.append(Paragraph("Physical Examination", styles['Heading3']))
            for key, value in assessment.physical_exam.items():
                if value: # Only add if the value is not None or empty
                    story.append(Paragraph(f"<b>{key.replace('_', ' ').title()}:</b> {value}", styles['Normal']))
            story.append(Spacer(1, 12))
            
        # Mental Status Examination
        if assessment.mental_status:
            story.append(Paragraph("Mental Status Examination (MSE)", styles['Heading3']))
            mental_status_data = assessment.mental_status
            story.append(Paragraph(f"<b>General Appearance:</b> {mental_status_data.get('general_appearance', 'N/A')}", styles['Normal']))
            story.append(Paragraph(f"<b>Psychomotor Activity:</b> {mental_status_data.get('psychomotor_activity', 'N/A')}", styles['Normal']))
            story.append(Paragraph(f"<b>Mood:</b> {mental_status_data.get('mood', 'N/A')}", styles['Normal']))
            story.append(Paragraph(f"<b>Affect:</b> {mental_status_data.get('affect', 'N/A')}", styles['Normal']))
            story.append(Paragraph(f"<b>Speech:</b> {mental_status_data.get('speech', 'N/A')}", styles['Normal']))
            story.append(Spacer(1, 12))
              

                # Cognitive Functions
        if assessment.cognitive_functions:
            story.append(Paragraph("Cognitive Functions", styles['Heading3']))
            cognitive_data = assessment.cognitive_functions
            story.append(Paragraph(f"<b>Attention & Concentration:</b> {cognitive_data.get('attention_concentration', 'N/A')}", styles['Normal']))
            story.append(Paragraph(f"<b>Orientation:</b> {cognitive_data.get('orientation', 'N/A')}", styles['Normal']))
            story.append(Paragraph(f"<b>Memory:</b> {cognitive_data.get('memory', 'N/A')}", styles['Normal']))
            story.append(Paragraph(f"<b>Arithmetic Ability:</b> {cognitive_data.get('arithmetic_ability', 'N/A')}", styles['Normal']))
            story.append(Paragraph(f"<b>Abstraction:</b> {cognitive_data.get('abstraction', 'N/A')}", styles['Normal']))
            story.append(Paragraph(f"<b>Judgement:</b> {cognitive_data.get('judgement', 'N/A')}", styles['Normal']))
            story.append(Paragraph(f"<b>Insight:</b> {cognitive_data.get('insight', 'N/A')}", styles['Normal']))
            story.append(Spacer(1, 12))

        # Clinical Scales
        if assessment.scales:
            story.append(Paragraph("Clinical Scales", styles['Heading3']))
            scales_data = assessment.scales
            # Iterate through the scales dictionary to print each one
            for scale_name, scale_value in scales_data.items():
                if scale_value != 'N/A':
                    story.append(Paragraph(f"<b>{scale_name}:</b> {scale_value}", styles['Normal']))
            story.append(Spacer(1, 12))  

        # **NEW: Review and Referral Section**
        if assessment.review_patient or assessment.referral:
            story.append(Paragraph("Review & Referral", styles['Heading3']))
            if assessment.review_patient:
                story.append(Paragraph(f"<b>Review Patient:</b> {assessment.review_patient}", styles['Normal']))
            if assessment.review_patient_details:
                story.append(Paragraph(f"<b>Review Details:</b> {assessment.review_patient_details}", styles['Normal']))
            if assessment.referral:
                story.append(Paragraph(f"<b>Referral:</b> {assessment.referral}", styles['Normal']))
            if assessment.referral_details:
                story.append(Paragraph(f"<b>Referral Details:</b> {assessment.referral_details}", styles['Normal']))
            story.append(Spacer(1, 12))

    # Diagnosis & Psychotherapy
    if treatment:
        story.append(Paragraph("Diagnosis & Psychotherapy", styles['Heading3']))
        if treatment.diagnosis:
            story.append(Paragraph(f"<b>Primary Diagnosis:</b> {treatment.diagnosis.get('primary_diagnosis', 'N/A')}", styles['Normal']))
            story.append(Paragraph(f"<b>Secondary Diagnosis:</b> {treatment.diagnosis.get('secondary_diagnosis', 'N/A')}", styles['Normal']))
        if treatment.psychotherapy:
            story.append(Paragraph(f"<b>Psychotherapy Plan:</b> {treatment.psychotherapy.get('psychotherapy_plan', 'N/A')}", styles['Normal']))
        story.append(Spacer(1, 12))

    # Lab Reports
    # Lab Reports
    if lab_report:
       story.append(Paragraph("Lab Reports and Scans", styles['Heading3']))
    
    # Add Test Summary
    
    
    if lab_report.tests and lab_report.tests.get('details'):
        story.append(Paragraph("<b>Lab Test Results:</b>", styles['Normal']))
        for test in lab_report.tests.get('details'):
            story.append(Paragraph(f"• {test.get('name')}: {test.get('value')}", styles['Normal']))
    story.append(Spacer(1, 12))

    if lab_report.tests and lab_report.tests.get('summary'):
        story.append(Paragraph(f"<b>Test Summary:</b> {lab_report.tests.get('summary')}", styles['Normal']))

    if lab_report.scans:
        scans = lab_report.scans
        # Add Scan Summary
        
            
        if scans.get('name'):
            story.append(Paragraph(f"<b>Scans Prescribed:</b> {scans.get('name')}", styles['Normal']))
        story.append(Spacer(1, 12))

        if scans.get('summary'):
            story.append(Paragraph(f"<b>Scan Summary:</b> {scans.get('summary')}", styles['Normal']))

    # Medications Table
    if treatment and treatment.medications:
        story.append(Paragraph("Medications", styles['Heading3']))
        med_data = [['Medication Name', 'Dose', 'Frequency', 'Instruction']]
        for med in treatment.medications:
            med_data.append([
                med.get('name', 'N/A'),
                med.get('dosage', 'N/A'),
                med.get('frequency', 'N/A'),
                med.get('instruction', 'N/A')
            ])
        
        table_style = TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e2eaf0')),
            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#E5E7EB')),
            ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#E5E7EB')),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold')
        ])
        med_table = Table(med_data, colWidths=[150, 70, 70, 150])
        med_table.setStyle(table_style)
        story.append(med_table)
        story.append(Spacer(1, 12))

    # Build the PDF document
    doc.build(story)
    
    # Get the value of the BytesIO buffer
    pdf_output = buffer.getvalue()
    buffer.close()
    
    # Create the response
    response = make_response(pdf_output)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=prescription_{uhid}.pdf'
    
    return response




# Add the route to serve the static chart images
@app.route('/static/images/charts/<filename>')
def serve_chart(filename):
    return send_from_directory(os.path.join(os.getcwd(), 'static/images/charts'), filename)

def setup_initial_admin():
    """
    Creates an initial admin user if one doesn't already exist.
    """
    with app.app_context():
        new_username = 'admin' 
        existing_user = User.query.filter_by(username=new_username).first()

        if existing_user:
            print(f"User '{new_username}' already exists. No new user created.")
        else:
            # Create and add the new user
            new_user = User(username=new_username)
            new_user.set_password('your_secure_password') # Replace with a strong password
            db.session.add(new_user)
            db.session.commit()
            print(f"User '{new_username}' added successfully.")


app.register_blueprint(radiology_bp, url_prefix='/radiology')
# This will make all routes in radiology_bp start with /radiology.
# For example, the / route becomes /radiology/
app.register_blueprint(labs_bp, url_prefix='/labs') # <-- Register the labs Blueprint

if __name__ == '__main__':
    with app.app_context():
        create_tables()
    app.run(debug=True)