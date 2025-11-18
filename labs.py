
#!/usr/bin/env python3
"""
test.py - Laboratory Test Request System for External Departments
This standalone Flask app allows other hospital departments to:
- Request lab tests from the Laboratory Management System
- Check request status
- View test results
- Download reports
"""

import os
import requests
import time
from datetime import datetime
from flask import Flask, request, render_template_string, send_from_directory, jsonify, session, redirect, url_for,Blueprint # <-- Import Blueprint
import secrets

DEFAULT_HOST = "http://127.0.0.1:5000"
SHARED_API_KEY = "hospital_shared_key"

labs_bp = Blueprint('labs_bp', __name__, template_folder="templates") # <-- Create the Blueprint


# Create a 'downloads' directory to store the test reports
os.makedirs("downloads", exist_ok=True)
HISTORY_PATH = os.path.join("downloads", "order_history.json")

# --- History Helpers ---
def load_history(department=None):
    if not os.path.exists(HISTORY_PATH):
        return []
    try:
        import json as _json
        with open(HISTORY_PATH, 'r', encoding='utf-8') as f:
            history = _json.load(f) or []
            
            # Filter by department if specified
            if department:
                history = [order for order in history if order.get('department') == department]
                
            return history
    except Exception:
        return []

def save_history(history):
    try:
        import json as _json
        with open(HISTORY_PATH, 'w', encoding='utf-8') as f:
            _json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def record_order(entry):
    history = load_history()
    history.insert(0, entry)
    save_history(history)

# --- Test Categories from Laboratory Management System ---
TEST_CATEGORIES = {
    'biochemistry': {
        'Kidney Function': ['GLU', 'UREA', 'CREATININE'],
        'Liver Function': ['SGOT', 'SGPT', 'ALBUMIN', 'TOTAL_BILIRUBIN'],
        'Thyroid Function': ['TSH', 'T3', 'T4'],
        'Cardiac Markers': ['TROPONIN_I'],
        'Lipid Profile': ['TOTAL_CHOLESTEROL', 'HDL', 'LDL'],
        'Electrolytes': ['SODIUM', 'POTASSIUM']
    },
    'microbiology': {
        'Wet Mount & Staining': ['GRAM_STAIN', 'HANGING_DROP', 'INDIA_INK', 'STOOL_OVA', 'KOH_MOUNT', 'ZN_STAIN'],
        'Culture & Sensitivity': ['BLOOD_CULTURE', 'URINE_CULTURE', 'SPUTUM_CULTURE', 'WOUND_CULTURE', 'THROAT_CULTURE', 'CSF_CULTURE'],
        'Fungal Culture': ['FUNGAL_CULTURE', 'FUNGAL_ID', 'ANTIFUNGAL_SENS'],
        'Serology': ['WIDAL', 'TYPHIDOT', 'DENGUE_NS1', 'MALARIA_AG', 'HIV_ELISA', 'HBSAG']
    },
    'pathology': {
        'Histopathology': ['BIOPSY_HISTOPATHOLOGY', 'SURGICAL_PATHOLOGY'],
        'Hematology': ['CBC', 'PERIPHERAL_SMEAR', 'BONE_MARROW', 'COAGULATION'],
        'Immunohistochemistry': ['IHC_MARKERS', 'SPECIAL_STAINS', 'MOLECULAR_PATH']
    }
}

# --- Helpers ---

def save_stream_to_file(resp, out_path, chunk_size=8192):
    """Saves a streaming response content to a file."""
    with open(out_path, 'wb') as f:
        for chunk in resp.iter_content(chunk_size):
            if chunk:
                f.write(chunk)

def download_report(host, order_id, out_dir, uhid=None):
    """Downloads a test report by order ID."""
    url = f"{host.rstrip('/')}/api/orders/{order_id}"
    try:
        with requests.get(url, stream=True, timeout=30, headers={'X-API-Key': SHARED_API_KEY}) as r:
            if r.ok:
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                fname = f"{uhid or 'patient'}_{order_id}_{ts}.json"
                
                out_path = os.path.join(out_dir, fname)
                save_stream_to_file(r, out_path)
                return fname
            else:
                return None
    except Exception:
        return None

def poll_request_status(host, order_id, timeout_s, poll_interval_s, out_dir, uhid):
    """Polls the status of a request until it's completed or times out."""
    status_url = f"{host.rstrip('/')}/api/orders/{order_id}"
    started = time.time()
    while time.time() - started < timeout_s:
        try:
            r = requests.get(status_url, timeout=15, headers={'X-API-Key': SHARED_API_KEY})
            if r.ok:
                j = r.json()
                # Check if any department has completed results
                per_dept = j.get('perDepartment', [])
                for dept in per_dept:
                    if dept.get('status') == 'completed' and dept.get('results'):
                        return download_report(host, order_id, out_dir, uhid)
        except requests.RequestException:
            # Ignore connection errors and continue polling
            pass
        time.sleep(poll_interval_s)
    return None

def perform_test_request(host, department, uhid, tests, priority='routine', specimen='Blood', clinical_notes=''):
    """Performs the API request to create a lab test order."""
    url = f"{host.rstrip('/')}/api/orders"
    payload = {
        "externalOrderId": f"EXT_{uhid}_{int(time.time())}",
        "priority": priority,
        "patient": {
            "uhid": uhid,
            "name": f"Patient {uhid}",
            "age": 30,
            "gender": "Not Specified"
        },
        "clinician": {
            "name": f"Dr. {department.title()}",
            "department": department,
            "contact": "Not Specified"
        },
        "tests": [{"testCode": test} for test in tests],
        "panels": [],
        "specimen": specimen,
        "clinicalNotes": clinical_notes
    }
    headers = {
        'Content-Type': 'application/json',
        'X-API-Key': SHARED_API_KEY
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=30)
    except requests.RequestException as e:
        return None, f"Request error: {e}"

    if resp.status_code == 201:
        j = resp.json()
        order_id = j.get('orderId')
        if order_id:
            # Record to local history
            record_order({
                'orderId': order_id,
                'externalOrderId': payload.get('externalOrderId'),
                'uhid': uhid,
                'department': department,
                'priority': priority,
                'tests': tests,
                'specimen': specimen,
                'createdAt': datetime.now().isoformat()
            })
            # Return the actual order ID from the main system
            return order_id, None
        else:
            return None, "No order ID received from server"
    
    return None, f"Server returned error {resp.status_code}: {resp.text[:400]}"

# --- Flask UI ---

def generate_test_form_html():
    """Generate the HTML form with proper test categories."""
    html = """<!DOCTYPE html>
<html>
<head>
    <title>Laboratory Test Request System</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://unpkg.com/feather-icons"></script>
</head>
<body class="bg-gray-100 min-h-screen">
    <div class="container mx-auto px-4 py-8">
        <!-- Header -->
        <div class="text-center mb-8">
            <h1 class="text-4xl font-bold text-gray-800 mb-2">Laboratory Test Request System</h1>
            <p class="text-gray-600">Request lab tests from the Central Laboratory Management System</p>
        </div>

        <!-- Main Form -->
        <div class="max-w-4xl mx-auto">
            <div class="bg-white shadow-lg rounded-xl p-8 mb-8">
                <h2 class="text-2xl font-semibold mb-6 text-gray-800">Test Request Form</h2>
                
                <form method="POST" action="{{ url_for('labs_bp.index') }}" class="space-y-6">

                    <!-- Department Display -->
                    <div>
                        <label class="block text-sm font-medium text-gray-700 mb-2">Requesting Department</label>
                        <div class="w-full border border-gray-300 rounded-lg px-4 py-3 bg-gray-50 flex justify-between items-center">
                            <span class="font-medium capitalize">{{ department }}</span>
                            
                        </div>
                    </div>

                    <!-- UHID -->
                    <div>
                        <label class="block text-sm font-medium text-gray-700 mb-2">Patient UHID</label>
                        <input type="text" name="uhid" class="w-full border border-gray-300 rounded-lg px-4 py-3 focus:ring-2 focus:ring-blue-500 focus:border-blue-500" placeholder="Enter Patient UHID" required>
                    </div>

                    <!-- Priority -->
                    <div>
                        <label class="block text-sm font-medium text-gray-700 mb-2">Priority</label>
                        <select name="priority" class="w-full border border-gray-300 rounded-lg px-4 py-3 focus:ring-2 focus:ring-blue-500 focus:border-blue-500" required>
                            <option value="routine">Routine</option>
                            <option value="urgent">Urgent</option>
                            <option value="stat">STAT (Immediate)</option>
                        </select>
                    </div>

                    <!-- Specimen -->
                    <div>
                        <label class="block text-sm font-medium text-gray-700 mb-2">Specimen Type</label>
                        <input type="text" name="specimen" class="w-full border border-gray-300 rounded-lg px-4 py-3 focus:ring-2 focus:ring-blue-500 focus:border-blue-500" placeholder="e.g., Blood, Urine, Tissue" value="Blood" required>
                    </div>

                    <!-- Clinical Notes -->
                    <div>
                        <label class="block text-sm font-medium text-gray-700 mb-2">Clinical Notes</label>
                        <textarea name="clinical_notes" rows="3" class="w-full border border-gray-300 rounded-lg px-4 py-3 focus:ring-2 focus:ring-blue-500 focus:border-blue-500" placeholder="Enter any clinical notes or special instructions"></textarea>
                    </div>

                    <!-- Test Selection -->
                    <div>
                        <label class="block text-sm font-medium text-gray-700 mb-4">Select Tests</label>"""
    
    # Add Biochemistry Tests
    html += """
                        <!-- Biochemistry Tests -->
                        <div class="mb-6">
                            <h3 class="text-lg font-medium text-gray-800 mb-3 flex items-center">
                                <i data-feather="flask" class="w-5 h-5 mr-2 text-blue-600"></i>
                                Biochemistry Tests
                            </h3>
                            <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">"""
    
    for category, tests in TEST_CATEGORIES['biochemistry'].items():
        html += f"""
                                <div class="border border-gray-200 rounded-lg p-4">
                                    <h4 class="font-medium text-gray-700 mb-2">{category}</h4>
                                    <div class="space-y-2">"""
        for test in tests:
            html += f"""
                                        <label class="flex items-center">
                                            <input type="checkbox" name="tests" value="{test}" class="rounded border-gray-300 text-blue-600 focus:ring-blue-500 test-checkbox" data-category="{category}" data-test="{test}">
                                            <span class="ml-2 text-sm text-gray-600">{test}</span>
                                        </label>"""
        html += """
                                    </div>
                                </div>"""
    
    # Add Microbiology Tests
    html += """
                        </div>

                        <!-- Microbiology Tests -->
                        <div class="mb-6">
                            <h3 class="text-lg font-medium text-gray-800 mb-3 flex items-center">
                                <i data-feather="microscope" class="w-5 h-5 mr-2 text-green-600"></i>
                                Microbiology Tests
                            </h3>
                            <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">"""
    
    for category, tests in TEST_CATEGORIES['microbiology'].items():
        html += f"""
                                <div class="border border-gray-200 rounded-lg p-4">
                                    <h4 class="font-medium text-gray-700 mb-2">{category}</h4>
                                    <div class="space-y-2">"""
        for test in tests:
            html += f"""
                                        <label class="flex items-center">
                                            <input type="checkbox" name="tests" value="{test}" class="rounded border-gray-300 text-blue-600 focus:ring-blue-500">
                                            <span class="ml-2 text-sm text-gray-600">{test}</span>
                                        </label>"""
        html += """
                                    </div>
                                </div>"""
    
    # Add Pathology Tests
    html += """
                        </div>

                        <!-- Pathology Tests -->
                        <div class="mb-6">
                            <h3 class="text-lg font-medium text-gray-800 mb-3 flex items-center">
                                <i data-feather="activity" class="w-5 h-5 mr-2 text-red-600"></i>
                                Pathology Tests
                            </h3>
                            <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">"""
    
    for category, tests in TEST_CATEGORIES['pathology'].items():
        html += f"""
                                <div class="border border-gray-200 rounded-lg p-4">
                                    <h4 class="font-medium text-gray-700 mb-2">{category}</h4>
                                    <div class="space-y-2">"""
        for test in tests:
            html += f"""
                                        <label class="flex items-center">
                                            <input type="checkbox" name="tests" value="{test}" class="rounded border-gray-300 text-blue-600 focus:ring-blue-500">
                                            <span class="ml-2 text-sm text-gray-600">{test}</span>
                                        </label>"""
        html += """
                                    </div>
                                </div>"""
    
    # Complete the form
    html += """
                        </div>
                    </div>

                    <!-- Submit Button -->
                    <div class="flex items-center justify-between">
                        <button type="submit" class="bg-blue-600 text-white px-6 py-3 rounded-lg hover:bg-blue-700 focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 transition-colors">
                            <i data-feather="send" class="w-5 h-5 mr-2 inline"></i>
                            Submit Test Request
                        </button>
                        <a href="{{ url_for('labs_bp.history_page') }}" class="text-blue-600 underline">View History</a>

                    </div>
                </form>
            </div>

            <!-- Results Section -->
            <div id="resultsSection" style="display: none;">
                <div class="bg-white shadow-lg rounded-xl p-8 mb-8">
                    <h2 class="text-2xl font-semibold mb-6 text-gray-800">Order Status</h2>
                    <div id="orderStatus" class="border w-full p-4 bg-gray-50 rounded">
                        <input type="hidden" id="currentOrderId" />
                        <div class="flex items-center justify-between">
                            <div>
                                <strong>Order ID:</strong> <span id="orderIdDisplay"></span><br>
                                <strong>Status:</strong> <span id="currentStatus" class="text-blue-600 font-medium">Queued</span>
                            </div>
                            <div class="flex space-x-2">
                                <button onclick="checkStatus()" class="bg-blue-500 text-white px-4 py-2 rounded hover:bg-blue-600">
                                    Check Status
                                </button>
                                <a id="viewResultsBtn" href="#" class="hidden bg-indigo-500 text-white px-4 py-2 rounded hover:bg-indigo-600">View Results</a>
                                <a href="{{ url_for('labs_bp.serve_report', filename=h.orderId) }}"
   class="bg-green-500 text-white px-4 py-2 rounded hover:bg-green-600 inline-block">
   Download Order
</a>

                            </div>
                        </div>
                        <div id="statusDetails" class="mt-3"></div>
                    </div>
                </div>
            </div>

            <!-- Instructions -->
            <div class="bg-blue-50 border border-blue-200 rounded-lg p-6">
                <h3 class="text-lg font-medium text-blue-800 mb-3 flex items-center">
                    <i data-feather="info" class="w-5 h-5 mr-2"></i>
                    How to Use This System
                </h3>
                <div class="text-blue-700 space-y-2">
                    <p>1. <strong>Select your department</strong> from the dropdown menu</p>
                    <p>2. <strong>Enter the patient's UHID</strong> (Unique Hospital ID)</p>
                    <p>3. <strong>Choose the priority level</strong> (Routine, Urgent, or STAT)</p>
                    <p>4. <strong>Select the specimen type</strong> (Blood, Urine, Tissue, etc.)</p>
                    <p>5. <strong>Add clinical notes</strong> if needed</p>
                    <p>6. <strong>Check the tests you want</strong> from the available categories</p>
                    <p>7. <strong>Submit the request</strong> - the system will automatically check for results</p>
                </div>
            </div>
        </div>
    </div>

    <script>
        // Initialize Feather icons
        feather.replace();
        
        // Form validation
        document.querySelector('form').addEventListener('submit', function(e) {
            const selectedTests = document.querySelectorAll('input[name="tests"]:checked');
            if (selectedTests.length === 0) {
                e.preventDefault();
                alert('Please select at least one test.');
                return false;
            }
        });

        // Status checking function
        function checkStatus() {
            const orderId = document.getElementById('currentOrderId').value;
            if (!orderId) return;

            // Show loading state
            const statusButton = event.target;
            const originalText = statusButton.innerHTML;
            statusButton.innerHTML = '<i data-feather="loader" class="w-4 h-4 mr-2 animate-spin"></i>Checking...';
            statusButton.disabled = true;
            feather.replace();

            fetch(`/api/status/${orderId}`)
                .then(response => response.json())
                .then(data => {
                    if (data.error) {
                        alert('Error checking status: ' + data.error);
                    } else {
                        // Update the status display
                        updateStatusDisplay(data);
                    }
                })
                .catch(error => {
                    alert('Error checking status: ' + error.message);
                })
                .finally(() => {
                    // Restore button state
                    statusButton.innerHTML = originalText;
                    statusButton.disabled = false;
                    feather.replace();
                });
        }

        function updateStatusDisplay(data) {
            const statusText = document.getElementById('currentStatus');
            const statusDetails = document.getElementById('statusDetails');
            const viewBtn = document.getElementById('viewResultsBtn');
            const orderId = document.getElementById('currentOrderId').value;
            
            if (statusText) {
                if (data.status === 'completed') {
                    statusText.textContent = 'Completed';
                    statusText.className = 'text-green-600 font-medium';
                    if (viewBtn && orderId) {
                        viewBtn.href = `/results/${orderId}`;
                        viewBtn.classList.remove('hidden');
                    }
                    // Show completed departments
                    statusDetails.innerHTML = `
                        <div class="mt-3 p-3 bg-green-100 rounded border border-green-300">
                            <h5 class="font-medium text-green-800 mb-2">✅ Completed Tests:</h5>
                            ${data.completedDepartments.map(dept => 
                                `<div class="text-sm text-green-700 mb-1">🏥 ${dept.department}: ${dept.results.length} results available</div>`
                            ).join('')}
                        </div>
                    `;
                } else {
                    statusText.textContent = 'In Progress';
                    statusText.className = 'text-yellow-600 font-medium';
                    if (viewBtn) viewBtn.classList.add('hidden');
                    // Show all departments and their status
                    statusDetails.innerHTML = `
                        <div class="mt-3 p-3 bg-yellow-100 rounded border border-yellow-300">
                            <h5 class="font-medium text-yellow-800 mb-2">🔄 Department Status:</h5>
                            ${data.allDepartments.map(dept => {
                                const statusIcon = dept.status === 'completed' ? '✅' : dept.status === 'in_progress' ? '🔄' : '⏳';
                                const statusColor = dept.status === 'completed' ? 'text-green-700' : dept.status === 'in_progress' ? 'text-yellow-700' : 'text-gray-700';
                                return `<div class="text-sm ${statusColor} mb-1">${statusIcon} ${dept.department}: ${dept.status}</div>`;
                            }).join('')}
                        </div>
                    `;
                }
            }
        }

        // Test selection logic - automatically select related tests
        document.addEventListener('DOMContentLoaded', function() {
            const testCheckboxes = document.querySelectorAll('.test-checkbox');
            
            testCheckboxes.forEach(checkbox => {
                checkbox.addEventListener('change', function() {
                    const category = this.dataset.category;
                    const test = this.dataset.test;
                    const isChecked = this.checked;
                    
                    // Define related tests for each category
                    const relatedTests = {
                        'Kidney Function': ['GLU', 'UREA', 'CREATININE'],
                        'Liver Function': ['SGOT', 'SGPT', 'ALBUMIN', 'TOTAL_BILIRUBIN'],
                        'Thyroid Function': ['TSH', 'T3', 'T4'],
                        'Lipid Profile': ['TOTAL_CHOLESTEROL', 'HDL', 'LDL']
                    };
                    
                    if (isChecked && relatedTests[category]) {
                        // When a test is selected, automatically select all tests in that category
                        relatedTests[category].forEach(relatedTest => {
                            const relatedCheckbox = document.querySelector(`input[value="${relatedTest}"]`);
                            if (relatedCheckbox && !relatedCheckbox.checked) {
                                relatedCheckbox.checked = true;
                                // Add visual indication that this was auto-selected
                                relatedCheckbox.classList.add('auto-selected');
                                const label = relatedCheckbox.nextElementSibling;
                                if (label) {
                                    label.innerHTML = `${label.textContent} <span class="text-xs text-gray-500">(auto-selected)</span>`;
                                }
                            }
                        });
                    } else if (!isChecked && relatedTests[category]) {
                        // When a test is unchecked, uncheck all tests in that category
                        relatedTests[category].forEach(relatedTest => {
                            const relatedCheckbox = document.querySelector(`input[value="${relatedTest}"]`);
                            if (relatedCheckbox) {
                                relatedCheckbox.checked = false;
                                relatedCheckbox.classList.remove('auto-selected');
                                const label = relatedCheckbox.nextElementSibling;
                                if (label) {
                                    label.innerHTML = label.textContent.replace(' <span class="text-xs text-gray-500">(auto-selected)</span>', '');
                                }
                            }
                        });
                    }
                });
            });
        });

        // Function to show results section after form submission
        function showResultsSection(orderId) {
            document.getElementById('resultsSection').style.display = 'block';
            document.getElementById('currentOrderId').value = orderId;
            document.getElementById('orderIdDisplay').textContent = orderId;
            document.getElementById('downloadOrderBtn').href = `/download/${orderId}`;
            
            // Scroll to results section
            document.getElementById('resultsSection').scrollIntoView({ behavior: 'smooth' });
        }
    </script>
</body>
</html>"""
    
    return html

HTML_FORM = generate_test_form_html()

# Create a login page for department selection
def generate_login_html(error=None):
    """Generate the HTML for the department login page."""
    html = """<!DOCTYPE html>
<html>
<head>
    <title>Department Login</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://unpkg.com/feather-icons"></script>
</head>
<body class="bg-gray-100 min-h-screen flex items-center justify-center">
    <div class="max-w-md w-full bg-white rounded-lg shadow-lg p-8">
        <div class="text-center mb-8">
            <h1 class="text-3xl font-bold text-gray-800 mb-2">Department Login</h1>
            <p class="text-gray-600">Select your department to access the Laboratory Test Request System</p>
        </div>
        
        <form method="POST" action="/login" class="space-y-6">
            <!-- Department Selection -->
            <div>
                <label class="block text-sm font-medium text-gray-700 mb-2">Department</label>
                <select name="department" class="w-full border border-gray-300 rounded-lg px-4 py-3 focus:ring-2 focus:ring-blue-500 focus:border-blue-500" required>
                    <option value="" disabled selected>Select Your Department</option>
                    <option value="surgery">Surgery</option>
                    <option value="cardiology">Cardiology</option>
                    <option value="neurology">Neurology</option>
                    <option value="orthopedics">Orthopedics</option>
                    <option value="pediatrics">Pediatrics</option>
                    <option value="emergency">Emergency</option>
                    <option value="icu">ICU</option>
                    <option value="general">General Medicine</option>
                </select>
            </div>
            
            <!-- Submit Button -->
            <div>
                <button type="submit" class="w-full bg-blue-600 text-white px-6 py-3 rounded-lg hover:bg-blue-700 focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 transition-colors">
                    <i data-feather="log-in" class="w-5 h-5 mr-2 inline"></i>
                    Login
                </button>
            </div>
        </form>
        
        <!-- Error Message -->
        {% if error %}
        <div class="mt-6 p-4 bg-red-100 border rounded text-red-700">
            <strong>Error:</strong> {{ error }}
        </div>
        {% endif %}
    </div>
    
    <script>
        // Initialize Feather icons
        feather.replace();
    </script>
</body>
</html>"""
    
    # If there was an error, add it to the page
    if error:
        html = html.replace('{% if error %}', '')
        html = html.replace('{% endif %}', '')
        html = html.replace('{{ error }}', error)
    else:
        html = html.replace('{% if error %}\n        <div class="mt-6 p-4 bg-red-100 border rounded text-red-700">\n            <strong>Error:</strong> {{ error }}\n        </div>\n        {% endif %}', '')
    
    return html

@labs_bp.route("/", methods=["GET", "POST"])
def index():
    if "department" not in session:
        session['department'] = 'psychiatry'  # default dept

    order_id, error = None, None

    if request.method == "POST":
        host = DEFAULT_HOST
        department = session.get("department")
        uhid = request.form.get("uhid")
        priority = request.form.get("priority")
        specimen = request.form.get("specimen")
        remarks = request.form.get("clinical_notes")
        selected_tests = request.form.getlist("tests")  # ✅ multiple tests

        if not all([department, uhid, selected_tests]):
            error = "UHID and at least one Test are required."
        else:
            try:
                def perform_test_request(host, department, uhid, selected_tests, priority, specimen, remarks):
                    order_id = secrets.token_hex(4)
                    history = load_history(department)
                    new_order = {
                        "orderId": order_id,
                        "department": department,
                        "uhid": uhid,
                        "tests": selected_tests,
                        "priority": priority,
                        "specimen": specimen,
                        "remarks": remarks,
                        "createdAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    }
                    history.append(new_order)
                    save_history(history)
                    return order_id, None

                order_id, error = perform_test_request(
                    host, department, uhid, selected_tests, priority, specimen, remarks
                )
            except Exception as e:
                error = f"An unexpected error occurred: {str(e)}"

    # ✅ History (no broken check_lab_status)
    hist = load_history(session.get('department'))
    statuses = {h['orderId']: "unknown" for h in hist}

    department = session.get('department', 'Unknown Department')
    html = generate_test_form_html()
    html = html.replace("{{ url_for('labs_bp.index') }}", url_for('labs_bp.index'))
    html = html.replace("{{ url_for('labs_bp.history_page') }}", url_for('labs_bp.history_page'))
    html = html.replace('{{ department }}', department)

    if error:
        html = html.replace('</form>', f"""
            </form>
            <div class="mt-6 p-4 bg-red-100 border rounded text-red-700">
                <strong>Error:</strong> {error}
            </div>""")

    if order_id:
        html = html.replace("</script>", f"""
            showResultsSection("{order_id}");
        </script>""")

    return html

@labs_bp.route("/api/status/<order_id>")
def check_order_status(order_id):
    """Check the status of an order (local mock + external API if available)."""
    try:
        # Try external system
        url = f"{DEFAULT_HOST.rstrip('/')}/api/orders/{order_id}"
        resp = requests.get(url, headers={'X-API-Key': SHARED_API_KEY}, timeout=10)
        if resp.ok:
            j = resp.json()
            per_dept = j.get('perDepartment', [])
            completed = [d for d in per_dept if d.get('status') == 'completed']
            return jsonify({
                "orderId": order_id,
                "status": "completed" if completed else "in_progress",
                "completedDepartments": completed,
                "allDepartments": per_dept
            })
    except Exception:
        pass  # ignore if external fails

    # Fallback to local history
    hist = load_history()
    for h in hist:
        if h["orderId"] == order_id:
            return jsonify({
                "orderId": order_id,
                "status": "queued",
                "completedDepartments": [],
                "allDepartments": [{"department": h["department"], "status": "queued"}]
            })
    return jsonify({"error": "Order not found"}), 404


@labs_bp.route("/api/order/<order_id>")
def api_get_order(order_id):
    try:
        r = requests.get(f"{DEFAULT_HOST.rstrip('/')}/api/orders/{order_id}", headers={'X-API-Key': SHARED_API_KEY}, timeout=20)
        return (r.text, r.status_code, {"Content-Type": r.headers.get('Content-Type', 'application/json')})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@labs_bp.route("/results/<order_id>")
def view_results(order_id):
    # Check if user is logged in with a department
    if 'department' not in session:
        return redirect(url_for('login'))
    
    current_department = session['department']
    
    # Check if the order exists in our history and belongs to the current department
    hist = load_history()
    order_exists = False
    order_belongs_to_department = False
    
    for order in hist:
        if order.get("orderId") == order_id:
            order_exists = True
            if order.get("department", "").lower() == current_department.lower():
                order_belongs_to_department = True
            break
    
    if not order_exists:
        error_page = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Error</title>
            <script src="https://cdn.tailwindcss.com"></script>
        </head>
        <body class="bg-gray-100 min-h-screen p-8">
            <div class="max-w-md mx-auto bg-white p-8 rounded-lg shadow-md">
                <h1 class="text-2xl font-bold text-red-600 mb-4">Error</h1>
                <p class="mb-4">Order ID {order_id} not found in history.</p>
                <a href="/history" class="text-blue-600">Return to History</a>
            </div>
        </body>
        </html>
        """
        return error_page, 404
    
    if not order_belongs_to_department:
        error_page = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Access Denied</title>
            <script src="https://cdn.tailwindcss.com"></script>
        </head>
        <body class="bg-gray-100 min-h-screen p-8">
            <div class="max-w-md mx-auto bg-white p-8 rounded-lg shadow-md">
                <h1 class="text-2xl font-bold text-red-600 mb-4">Access Denied</h1>
                <p class="mb-4">You do not have permission to view results for this order.</p>
                <p class="mb-4">This order belongs to another department.</p>
                <a href="{{ url_for('labs_bp.history_page') }}" class="text-blue-600 underline">Return to History</a>
            </div>
        </body>
        </html>
        """
        return error_page, 403
        
    try:
        r = requests.get(f"{DEFAULT_HOST.rstrip('/')}/api/orders/{order_id}", headers={'X-API-Key': SHARED_API_KEY}, timeout=20)
        if not r.ok:
            error_page = render_template_string("""
            <!DOCTYPE html><html><head><title>Results</title><script src=\"https://cdn.tailwindcss.com\"></script></head>
            <body class=\"bg-gray-100 p-8\"><div class=\"max-w-5xl mx-auto bg-white p-6 rounded shadow\">
            <h1 class=\"text-2xl font-semibold mb-4\">Results</h1>
            <div class=\"text-red-600\">Failed to load results (status: {{status}})</div>
            <a class=\"mt-4 inline-block text-blue-600\" href=\"/\">Back</a></div></body></html>""", status=r.status_code)
            return error_page, r.status_code
        data = r.json()
        return render_template_string("""
<!DOCTYPE html>
<html>
        <head>
            <title>Order {{ data.orderId }} Results</title>
            <script src="https://cdn.tailwindcss.com"></script>
            <script src="https://unpkg.com/feather-icons"></script>
        </head>
        <body class="bg-gray-100 min-h-screen">
            <div class="max-w-6xl mx-auto p-6">
                <div class="mb-6 flex items-center justify-between">
                    <h1 class="text-2xl font-bold">Order Results • {{ data.orderId }}</h1>
                    <a href="/" class="text-blue-600">Back to Request Form</a>
                </div>
                <div class="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-6">
                    <div class="bg-white p-4 rounded shadow">
                        <div class="text-sm text-gray-500">Patient</div>
                        <div class="font-medium">{{ data.patient.name if data.patient else 'N/A' }}</div>
                    </div>
                    <div class="bg-white p-4 rounded shadow">
                        <div class="text-sm text-gray-500">Priority</div>
                        <div class="font-medium">{{ (data.priority or 'routine').upper() }}</div>
                    </div>
                    <div class="bg-white p-4 rounded shadow">
                        <div class="text-sm text-gray-500">Requested</div>
                        <div class="font-medium">{{ data.receivedAt }}</div>
                    </div>
                </div>
                {% for dept in data.perDepartment %}
                <div class="bg-white p-5 rounded shadow mb-6">
                    <div class="flex items-center justify-between mb-3">
                        <h2 class="text-lg font-semibold">{{ dept.department|title }}</h2>
                        <span class="text-sm px-2 py-1 rounded {{ 'bg-green-100 text-green-700' if dept.status=='completed' else 'bg-yellow-100 text-yellow-700' }}">{{ dept.status.replace('_',' ') }}</span>
                    </div>
                    {% if dept.results and dept.results|length > 0 %}
                        {% if dept.department == 'biochemistry' %}
                            <div class="overflow-x-auto">
                                <table class="min-w-full text-sm">
                                    <thead><tr class="text-left border-b"><th class="py-2 pr-4">Test</th><th class="py-2 pr-4">Value</th><th class="py-2 pr-4">Unit</th><th class="py-2 pr-4">Flag</th><th class="py-2">Ref Range</th></tr></thead>
                                    <tbody>
                                        {% for r in dept.results %}
                                        <tr class="border-b">
                                            <td class="py-2 pr-4">{{ r.testCode }}</td>
                                            <td class="py-2 pr-4">{{ r.value }}</td>
                                            <td class="py-2 pr-4">{{ r.unit }}</td>
                                            <td class="py-2 pr-4">{{ r.flag }}</td>
                                            <td class="py-2">{{ (r.referenceRange.low if r.referenceRange else '') }} - {{ (r.referenceRange.high if r.referenceRange else '') }}</td>
                                        </tr>
                                        {% endfor %}
                                    </tbody>
                                </table>
                            </div>
                            {% if dept.results[0].impression %}
                                <div class="mt-4"><div class="text-sm text-gray-600">Impression</div><div class="font-medium">{{ dept.results[0].impression }}</div></div>
                            {% endif %}
                        {% elif dept.department == 'microbiology' %}
                            {% set r = dept.results[0] %}
                            <div class="space-y-3">
                                <div><div class="text-sm text-gray-600">Findings</div><div class="whitespace-pre-wrap">{{ r.findings }}</div></div>
                                <div><div class="text-sm text-gray-600">Abnormal / Significant Findings</div><div class="whitespace-pre-wrap">{{ r.abnormalFindings }}</div></div>
                                <div><div class="text-sm text-gray-600">Impression</div><div class="whitespace-pre-wrap">{{ r.impression }}</div></div>
                            </div>
                        {% elif dept.department == 'pathology' %}
                            {% set r = dept.results[0] %}
                            <div class="space-y-3">
                                <div><div class="text-sm text-gray-600">Name of surgery</div><div class="whitespace-pre-wrap">{{ r.surgeryName }}</div></div>
                                <div><div class="text-sm text-gray-600">Nature of specimen</div><div class="whitespace-pre-wrap">{{ r.specimenNature }}</div></div>
                                <div><div class="text-sm text-gray-600">Intraoperative findings</div><div class="whitespace-pre-wrap">{{ r.intraoperativeFindings }}</div></div>
                                <div><div class="text-sm text-gray-600">Gross findings</div><div class="whitespace-pre-wrap">{{ r.grossFindings }}</div></div>
                                <div><div class="text-sm text-gray-600">Microscopic examination</div><div class="whitespace-pre-wrap">{{ r.microscopicExamination }}</div></div>
                                <div><div class="text-sm text-gray-600">Signature of the reporting doctor</div><div class="whitespace-pre-wrap">{{ r.reportingDoctor }}</div></div>
                            </div>
                        {% else %}
                            <pre class="text-xs bg-gray-50 p-3 rounded">{{ dept.results|tojson }}</pre>
                        {% endif %}
                    {% else %}
                        <div class="text-gray-500 text-sm">No results yet.</div>
                    {% endif %}
                </div>
                {% endfor %}
            </div>
        </body>
        </html>
        """, data=data)
    except Exception as e:
        return render_template_string("""<!DOCTYPE html><html><body><pre>{{e}}</pre></body></html>""", e=str(e))

@labs_bp.route("/download/<path:filename>")
def serve_report(filename):
    """Serves the downloaded test report from the 'downloads' directory."""
    # Check if user is logged in with a department
    if 'department' not in session:
        return redirect(url_for('login'))
    
    current_department = session['department']
    
    # Check if the order exists in our history and belongs to the current department
    hist = load_history()
    order_exists = False
    order_belongs_to_department = False
    
    for order in hist:
        if order.get("orderId") == filename:
            order_exists = True
            if order.get("department", "").lower() == current_department.lower():
                order_belongs_to_department = True
            break
    
    if not order_exists:
        error_page = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Error</title>
            <script src="https://cdn.tailwindcss.com"></script>
        </head>
        <body class="bg-gray-100 min-h-screen p-8">
            <div class="max-w-md mx-auto bg-white p-8 rounded-lg shadow-md">
                <h1 class="text-2xl font-bold text-red-600 mb-4">Error</h1>
                <p class="mb-4">Order ID {filename} not found in history.</p>
                <a href="/history" class="text-blue-600">Return to History</a>
            </div>
        </body>
        </html>
        """
        return error_page, 404
    
    if not order_belongs_to_department:
        error_page = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Access Denied</title>
            <script src="https://cdn.tailwindcss.com"></script>
        </head>
        <body class="bg-gray-100 min-h-screen p-8">
            <div class="max-w-md mx-auto bg-white p-8 rounded-lg shadow-md">
                <h1 class="text-2xl font-bold text-red-600 mb-4">Access Denied</h1>
                <p class="mb-4">You do not have permission to download this report.</p>
                <p class="mb-4">This report belongs to another department.</p>
                <a href="/history" class="text-blue-600">Return to History</a>
            </div>
        </body>
        </html>
        """
        return error_page, 403
    
    # Create a simple order details file for any order ID
    order_details = f"""Laboratory Test Order Details
==============================

Order ID: {filename}
Requested At: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Status: Queued
Department: {current_department}

This order has been successfully submitted to the Laboratory Management System.
You can check the status using the "Check Status" button.

For any questions, please contact the laboratory department.
"""
    
    # Create a temporary file
    temp_file = os.path.join("downloads", f"order_{filename}.txt")
    with open(temp_file, 'w') as f:
        f.write(order_details)
    
    return send_from_directory("downloads", f"order_{filename}.txt", as_attachment=True)

@labs_bp.route("/history")
def history_page():
    # Check if department is selected
    if "department" not in session:
        return redirect(url_for("login"))
        
    # Get the current department from session
    department = session.get("department")
    
    # Load history filtered by department
    hist = load_history(department)
    # fetch status for each order (best-effort, non-blocking style)
    statuses = {}
    for h in hist[:20]:  # limit to last 20 for speed
        try:
            r = requests.get(f"{DEFAULT_HOST.rstrip('/')}/api/orders/{h['orderId']}", headers={'X-API-Key': SHARED_API_KEY}, timeout=5)
            if r.ok:
                j = r.json()
                per = j.get('perDepartment', [])
                any_completed = any(d.get('status') == 'completed' for d in per)
                statuses[h['orderId']] = 'completed' if any_completed else 'in_progress'
            else:
                statuses[h['orderId']] = 'unknown'
        except Exception:
            statuses[h['orderId']] = 'unknown'
    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Order History</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <script src="https://unpkg.com/feather-icons"></script>
    </head>
    <body class="bg-gray-100 min-h-screen">
        <div class="max-w-6xl mx-auto p-6">
            <div class="flex items-center justify-between mb-6">
                <div>
                    <h1 class="text-2xl font-bold">Order History</h1>
                    <p class="text-gray-600">Department: <span class="font-medium capitalize">{{ department }}</span></p>
                </div>
                <div class="space-x-2">
                    <a class="text-blue-600" href="/">New Request</a>
                    <a class="text-gray-600" href="/logout">Logout</a>
                </div>
            </div>
            <div class="bg-white rounded shadow overflow-hidden">
                <table class="min-w-full text-sm">
                    <thead class="bg-gray-50 text-gray-600">
                        <tr>
                            <th class="text-left px-4 py-2">Order ID</th>
                            <th class="text-left px-4 py-2">UHID</th>
                            <th class="text-left px-4 py-2">Dept</th>
                            <th class="text-left px-4 py-2">Priority</th>
                            <th class="text-left px-4 py-2">Created</th>
                            <th class="text-left px-4 py-2">Status</th>
                            <th class="text-left px-4 py-2">Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for h in hist %}
                        <tr class="border-t">
                            <td class="px-4 py-2 font-medium">{{ h.orderId }}</td>
                            <td class="px-4 py-2">{{ h.uhid }}</td>
                            <td class="px-4 py-2 capitalize">{{ h.department }}</td>
                            <td class="px-4 py-2 uppercase">{{ h.priority }}</td>
                            <td class="px-4 py-2">{{ h.createdAt }}</td>
                            {% set st = statuses.get(h.orderId, 'unknown') %}
                            <td class="px-4 py-2">
                                <span class="px-2 py-1 rounded text-xs {{ 'bg-green-100 text-green-700' if st=='completed' else ('bg-yellow-100 text-yellow-700' if st=='in_progress' else 'bg-gray-100 text-gray-700') }}">{{ st.replace('_',' ') }}</span>
                            </td>
                            <td class="px-4 py-2 space-x-2">
    <a class="inline-block bg-blue-600 text-white px-3 py-1 rounded hover:bg-blue-700 transition" 
       href="{{ url_for('labs_bp.view_results', order_id=h.orderId) }}">View Results</a>
    
    <a class="inline-block bg-green-600 text-white px-3 py-1 rounded hover:bg-green-700 transition" 
       href="{{ url_for('labs_bp.serve_report', filename=h.orderId) }}">View Report</a>
    
    <button class="inline-block bg-gray-600 text-white px-3 py-1 rounded hover:bg-gray-700 transition"
        onclick="checkStatus('{{ h.orderId }}')">
    Check Status
</button>


                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
            {% if not hist %}
                <div class="mt-6 text-gray-600">No orders submitted yet from this client.</div>
            {% endif %}
        </div>
        <script>
function checkStatus(orderId){
    // Use Flask url_for to generate the correct route, replacing the placeholder with actual orderId
    const url = '{{ url_for("labs_bp.check_order_status", order_id="__ORDER__") }}'.replace('__ORDER__', orderId);

    fetch(url)
        .then(response => {
            if (!response.ok) throw new Error('HTTP error ' + response.status);
            return response.json();
        })
        .then(data => {
            let msg = `Order ID: ${data.orderId}\nStatus: ${data.status}`;
            if(data.completedDepartments && data.completedDepartments.length > 0){
                msg += "\nCompleted Departments: " + data.completedDepartments.map(d => d.department).join(', ');
            }
            alert(msg);
        })
        .catch(err => {
            alert('Failed to fetch status: ' + err);
        });
}
</script>


                                  
    </body>
    </html>
    """, hist=hist, statuses=statuses, department=department)

@labs_bp.route("/api/health")
def health():
    """Health check endpoint."""
    return jsonify({
        'status': 'OK',
        'service': 'Laboratory Test Request System',
        'timestamp': datetime.now().isoformat(),
        'target_host': DEFAULT_HOST
    })

if __name__ == "__main__":
    print("🚀 Starting Laboratory Test Request System...")
    print(f"📡 Target Laboratory System: {DEFAULT_HOST}")
    print(f"🔑 Using API Key: {SHARED_API_KEY}")
    print(f"🌐 Web Interface: http://localhost:8000")
    print(f"📁 Downloads Directory: {os.path.abspath('downloads')}")
    print("\n" + "="*60)
    print("This system allows other departments to request lab tests")
    print("from your Laboratory Management System via API calls.")
    print("="*60 + "\n")
    
    # Runs the Flask app on port 8000
    app.run(port=8000, debug=True, host='0.0.0.0')
