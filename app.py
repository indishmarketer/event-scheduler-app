# app.py
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, abort
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import threading, time, os, requests

app = Flask(__name__)
app.secret_key = os.environ.get("APP_SECRET","change_this_secret")
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///events.db'
db = SQLAlchemy(app)

# Models
class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200))
    event_datetime = db.Column(db.String(50))   # stored as "YYYY-MM-DD HH:MM"
    publish_datetime = db.Column(db.String(50)) # stored as "YYYY-MM-DD HH:MM"
    display_text = db.Column(db.Text)
    deadline = db.Column(db.String(50))         # stored as "YYYY-MM-DD HH:MM:SS" (for countdown)
    sent = db.Column(db.Boolean, default=False)

# WordPress config from env
WP_URL = os.environ.get("WP_URL")
WP_USER = os.environ.get("WP_USER")
WP_APP_PASSWORD = os.environ.get("WP_APP_PASSWORD")
EVENT_PAGE_ID = int(os.environ.get("EVENT_PAGE_ID","0"))
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD","adminpass")
CHECK_INTERVAL = int(os.environ.get("CHECK_INTERVAL_SECONDS","60"))

# helper to parse datetime
def parse_dt(s):
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M")
    except:
        try:
            return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
        except:
            return None

def send_to_wordpress(text, deadline=None):
    if not WP_URL or not WP_USER or not WP_APP_PASSWORD or not EVENT_PAGE_ID:
        print("WP credentials or page id missing")
        return False, "WP not configured"
    url = f"{WP_URL.rstrip('/')}/wp-json/im/v1/update-event"
    payload = {"page_id": EVENT_PAGE_ID, "value": text}
    if deadline:
        payload["deadline"] = deadline
    try:
        r = requests.post(url, auth=(WP_USER, WP_APP_PASSWORD), json=payload, timeout=15)
        return r.ok, r.text
    except Exception as e:
        return False, str(e)

def scheduler_loop():
    print("Scheduler started, checking every", CHECK_INTERVAL, "seconds")
    while True:
        now = datetime.now()
        events = Event.query.filter_by(sent=False).all()
        for ev in events:
            pd = parse_dt(ev.publish_datetime)
            if pd and pd <= now:
                ok, resp = send_to_wordpress(ev.display_text, ev.deadline)
                if ok:
                    ev.sent = True
                    db.session.commit()
                    print(f"Sent event {ev.id} at {now}")
                else:
                    print("Failed to send event", ev.id, resp)
        time.sleep(CHECK_INTERVAL)

@app.route("/")
def index():
    # simple homepage redirect to admin
    return redirect(url_for('admin'))

@app.route("/admin", methods=["GET"])
def admin():
    # simple auth using password in query or cookie (very basic)
    pw = request.args.get("pw","")
    if pw != ADMIN_PASSWORD:
        return render_template("login.html")
    events = Event.query.order_by(Event.event_datetime).all()
    return render_template("admin.html", events=events, pw=pw)

@app.route("/login", methods=["POST"])
def login():
    pw = request.form.get("password","")
    if pw == ADMIN_PASSWORD:
        return redirect(url_for("admin", pw=pw))
    flash("Wrong password")
    return redirect(url_for("admin"))

@app.route("/create", methods=["POST"])
def create():
    pw = request.form.get("pw","")
    if pw != ADMIN_PASSWORD:
        abort(403)
    name = request.form.get("name")
    event_dt = request.form.get("event_datetime")
    pub_dt = request.form.get("publish_datetime")
    display = request.form.get("display_text")
    deadline = request.form.get("deadline")
    ev = Event(name=name, event_datetime=event_dt, publish_datetime=pub_dt,
               display_text=display, deadline=deadline, sent=False)
    db.session.add(ev)
    db.session.commit()
    flash("Event created")
    return redirect(url_for("admin", pw=pw))

@app.route("/delete/<int:eid>")
def delete(eid):
    pw = request.args.get("pw","")
    if pw != ADMIN_PASSWORD:
        abort(403)
    ev = Event.query.get_or_404(eid)
    db.session.delete(ev)
    db.session.commit()
    flash("Event deleted")
    return redirect(url_for("admin", pw=pw))

@app.route("/api/events")
def api_events():
    # Optional: return JSON list of events (for debugging)
    evs = Event.query.all()
    return jsonify([{
        "id": e.id,
        "name": e.name,
        "event_datetime": e.event_datetime,
        "publish_datetime": e.publish_datetime,
        "display_text": e.display_text,
        "deadline": e.deadline,
        "sent": e.sent
    } for e in evs])

if __name__ == "__main__":
    # ensure DB exists
    with app.app_context():
        db.create_all()
    # start scheduler in background thread
    t = threading.Thread(target=scheduler_loop, daemon=True)
    t.start()
    app.run(host='0.0.0.0', port=5000)
