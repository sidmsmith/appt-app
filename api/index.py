# api/index.py
from flask import Flask, request, jsonify, send_from_directory
import json, re, os, traceback
from datetime import datetime
import requests
from requests.auth import HTTPBasicAuth
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)

# === SECURE CONFIG (from Vercel Environment Variables) ===
HA_WEBHOOK_URL = "http://sidmsmith.zapto.org:8123/api/webhook/manhattan_appt"
HA_HEADERS = {"Content-Type": "application/json"}

AUTH_HOST = "salep-auth.sce.manh.com"
API_HOST = "salep.sce.manh.com"
USERNAME_BASE = "sdtadmin@"
PASSWORD = os.getenv("MANHATTAN_PASSWORD")
CLIENT_ID = "omnicomponent.1.0.0"
CLIENT_SECRET = os.getenv("MANHATTAN_SECRET")

# Critical: Fail fast if secrets missing
if not PASSWORD or not CLIENT_SECRET:
    raise Exception("Missing MANHATTAN_PASSWORD or MANHATTAN_SECRET environment variables")

STATUS_MAP = {
    "1000": "Requested", "2000": "Countered", "3000": "Scheduled",
    "4000": "Checked In", "8000": "Complete", "9000": "Cancelled"
}

# === HELPERS ===
def send_ha_message(payload):
    try:
        requests.post(HA_WEBHOOK_URL, json=payload, headers=HA_HEADERS, timeout=5)
    except:
        pass

def get_manhattan_token(org):
    url = f"https://{AUTH_HOST}/oauth/token"
    username = f"{USERNAME_BASE}{org.lower()}"
    data = {
        "grant_type": "password",
        "username": username,
        "password": PASSWORD,
    }
    auth = HTTPBasicAuth(CLIENT_ID, CLIENT_SECRET)
    try:
        r = requests.post(
            url,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            auth=auth,
            timeout=30,
            verify=False,
        )
        r.raise_for_status()
        return r.json().get("access_token")
    except:
        return None

def search_single(criteria, headers, org):
    url = f"https://{API_HOST}/appointment/api/appointment/appointment/search"
    headers = headers.copy()
    headers.update({
        "Content-Type": "application/json",
        "selectedOrganization": org,
        "selectedLocation": f"{org}-DM1"
    })
    value = criteria.strip().strip("'\"")
    if not value:
        return []
    query = f"(AppointmentId = '{value}' OR CarrierId = '{value}' OR TrailerId = '{value}' OR AppointmentContents.BillOfLadingNumber = '{value}')"
    payload = {
        "Query": query,
        "Size": 1000,
        "Page": 0
    }
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=30, verify=False)
        return r.json().get("data", []) if r.ok else []
    except:
        return []

def check_in_trailer(appt_data, headers, org):
    url = f"https://{API_HOST}/yard-management/api/yard-management/transaction/trailer/checkIn"
    headers = headers.copy()
    headers.update({
        "Content-Type": "application/json",
        "selectedOrganization": org,
        "selectedLocation": f"{org}-DM1"
    })
    appt_type = appt_data.get("AppointmentTypeId", "")
    payload = {
        "AppointmentInfo": {
            "AppointmentId": appt_data.get("AppointmentId"),
            "AppointmentTypeId": appt_type
        },
        "VisitType": appt_type,
        "TrailerInfo": {
            "CarrierId": appt_data.get("CarrierId"),
            "TrailerId": appt_data.get("TrailerId"),
            "EquipmentTypeId": appt_data.get("EquipmentTypeId")
        }
    }
    
    # TODO: Add validation for ASN and Shipment if specified on appointment
    # If appt_data contains ASN (e.g., appt_data.get("ASN") or appt_data.get("AsnId")),
    # validate that the ASN exists in the system using the appropriate API endpoint.
    # If appt_data contains Shipment (e.g., appt_data.get("ShipmentId") or appt_data.get("Shipment")),
    # validate that the Shipment exists in the system using the appropriate API endpoint.
    # Return an error response if validation fails before proceeding with check-in.
    
    # Log the request payload (raw JSON)
    try:
        payload_json = json.dumps(payload, indent=2)
        print(f"[CHECK-IN REQUEST] URL: {url}")
        print(f"[CHECK-IN REQUEST] Organization: {org}")
        print(f"[CHECK-IN REQUEST] Appointment ID: {appt_data.get('AppointmentId')}")
        print(f"[CHECK-IN REQUEST] Raw JSON Payload Sent:")
        print(payload_json)
    except Exception as log_err:
        print(f"[CHECK-IN REQUEST] Error logging payload: {str(log_err)}")
        print(f"[CHECK-IN REQUEST] Payload (fallback): {payload}")
    
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=30, verify=False)
        
        # Log the full response details
        print(f"[CHECK-IN RESPONSE] Status Code: {r.status_code}")
        print(f"[CHECK-IN RESPONSE] Response Headers: {dict(r.headers)}")
        print(f"[CHECK-IN RESPONSE] Raw Response Text (first 5000 chars):")
        print(r.text[:5000])
        
        try:
            response_json = r.json()
            print(f"[CHECK-IN RESPONSE] Parsed JSON Response:")
            print(json.dumps(response_json, indent=2))
        except Exception as json_err:
            print(f"[CHECK-IN RESPONSE] Failed to parse JSON: {str(json_err)}")
            response_json = {"raw_text": r.text[:2000]}

        if r.ok and response_json.get("success"):
            msg_list = response_json.get("messages", {}).get("Message", [])
            description = next((m.get("Description") for m in msg_list if m.get("Description")), "Check-in successful")
            print(f"[CHECK-IN SUCCESS] Message: {description}")
            return {"success": True, "message": description}
        else:
            # Log failure details
            print(f"[CHECK-IN FAILURE] Status OK: {r.ok}, Success in JSON: {response_json.get('success')}")
            err_list = response_json.get("errors", []) or response_json.get("exceptions", [])
            err_msg = err_list[0].get("message") if err_list else "Unknown error"
            print(f"[CHECK-IN FAILURE] Error Message: {err_msg}")
            print(f"[CHECK-IN FAILURE] Full Error Details:")
            print(json.dumps(response_json, indent=2))
            return {"success": False, "error": err_msg}
    except Exception as e:
        # Log exception with full traceback
        print(f"[CHECK-IN EXCEPTION] Request failed with exception:")
        print(f"[CHECK-IN EXCEPTION] Exception Type: {type(e).__name__}")
        print(f"[CHECK-IN EXCEPTION] Exception Message: {str(e)}")
        print(f"[CHECK-IN EXCEPTION] Full Traceback:")
        print(traceback.format_exc())
        return {"success": False, "error": f"Request failed: {str(e)}"}

def format_date(date_str):
    if not date_str:
        return "—"
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return dt.strftime("%m/%d %I:%M %p").lstrip("0")
    except:
        return "—"

def format_status(status_id):
    return STATUS_MAP.get(status_id, "Unknown")

# === API ROUTES ===
@app.route('/api/app_opened', methods=['POST'])
def app_opened():
    send_ha_message({"event": "manhattan_appt_open", "org": request.json.get("org", "")})
    return jsonify({"success": True})

@app.route('/api/auth', methods=['POST'])
def auth():
    org = request.json.get('org', '').strip()
    if not org:
        return jsonify({"success": False, "error": "ORG required"})
    token = get_manhattan_token(org)
    if token:
        send_ha_message({"event": "manhattan_appt_auth", "org": org, "success": True})
        return jsonify({"success": True, "token": token})
    send_ha_message({"event": "manhattan_appt_auth", "org": org, "success": False})
    return jsonify({"success": False, "error": "Auth failed"})

@app.route('/api/search', methods=['POST'])
def search():
    org = request.json.get('org')
    criteria_input = request.json.get('criteria', '')
    token = request.json.get('token')
    if not all([org, criteria_input, token]):
        return jsonify({"success": False, "error": "Missing data"})

    headers = {"Authorization": f"Bearer {token}"}
    raw_values = re.split(r'[,\s;]+', criteria_input)
    criteria_list = [v.strip().strip("'\"") for v in raw_values if v.strip() and v.strip("'\"")]
    if not criteria_list:
        return jsonify({"success": False, "error": "No valid criteria"})

    per_criteria = {}
    all_appts = {}
    seen_ids = set()

    for crit in criteria_list:
        results = search_single(crit, headers, org)
        per_criteria[crit] = len(results)
        for appt in results:
            appt_id = appt.get("AppointmentId")
            if appt_id and appt_id not in seen_ids:
                all_appts[appt_id] = appt
                seen_ids.add(appt_id)

    final_results = list(all_appts.values())
    for appt in final_results:
        appt['ScheduledDate'] = format_date(appt.get('PreferredDateTime'))
        appt['StatusText'] = format_status(appt.get('AppointmentStatusId'))

    send_ha_message({
        "event": "manhattan_appt_search",
        "org": org,
        "criteria": criteria_input,
        "totalCount": len(final_results)
    })

    return jsonify({
        "success": True,
        "results": final_results,
        "per_criteria": per_criteria
    })

@app.route('/api/checkin', methods=['POST'])
def checkin():
    appt = request.json.get('appt')
    org = request.json.get('org')
    token = request.json.get('token')
    if not all([appt, org, token]):
        return jsonify({"success": False, "error": "Missing data"})

    headers = {"Authorization": f"Bearer {token}"}
    result = check_in_trailer(appt, headers, org)
    send_ha_message({
        "event": "manhattan_appt_checkin",
        "org": org,
        "appt_id": appt.get("AppointmentId"),
        "success": result.get("success")
    })
    return jsonify(result)

@app.route('/api/statsig-config', methods=['GET'])
def statsig_config():
    """Provide Statsig Client SDK Key to client-side code"""
    client_key = os.getenv('STATSIG_CLIENT_KEY')
    if client_key:
        return jsonify({"key": client_key})
    else:
        return jsonify({
            "error": "STATSIG_CLIENT_KEY not configured",
            "note": "Please set STATSIG_CLIENT_KEY environment variable in Vercel project settings. The key should start with 'client-'"
        }), 200  # Return 200 so client can handle gracefully

@app.route('/statsig-js-client.min.js', methods=['GET'])
def serve_statsig_sdk():
    """Serve Statsig SDK JavaScript file"""
    sdk_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'statsig-js-client.min.js')
    if os.path.exists(sdk_path):
        return send_from_directory(os.path.dirname(os.path.dirname(__file__)), 'statsig-js-client.min.js', mimetype='application/javascript')
    return jsonify({'error': 'SDK file not found'}), 404

@app.route('/statsig.js', methods=['GET'])
def serve_statsig_js():
    """Serve Statsig integration JavaScript file"""
    statsig_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'statsig.js')
    if os.path.exists(statsig_path):
        return send_from_directory(os.path.dirname(os.path.dirname(__file__)), 'statsig.js', mimetype='application/javascript')
    return jsonify({'error': 'Statsig script not found'}), 404

# === FALLBACK: Serve index.html for SPA (Critical for Vercel) ===
@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve_static(path):
    if path.startswith('api/'):
        return "API route not found", 404
    # Don't serve index.html for JavaScript files that don't exist - return 404 instead
    if path.endswith('.js') and path not in ['statsig.js', 'statsig-js-client.min.js']:
        return jsonify({'error': 'File not found'}), 404
    try:
        return send_from_directory('..', 'index.html')
    except:
        return "File not found", 404

# === DEV SERVER ===
if __name__ == '__main__':
    app.run(port=5000, debug=True)