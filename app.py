from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import pandas as pd
import os

app = Flask(__name__)
app.secret_key = 'cmech_secret_2024'

# ── Database ──────────────────────────────────────────────────────────────────
# Replace the value below with your actual Aiven PostgreSQL URI.
# Format: postgresql://user:password@host:port/dbname?sslmode=require
DATABASE_URI = os.environ.get(
    'DATABASE_URL',
    'postgres://avnadmin:AVNS_CtetCR3pGEtu6PkKMPF@pg-2069df69-abhinab2k05-55ab.f.aivencloud.com:22126/defaultdb?sslmode=require'
)
# Flask-SQLAlchemy requires 'postgresql://' not 'postgres://'
app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URI.replace('postgres://', 'postgresql://')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# ── Model ─────────────────────────────────────────────────────────────────────
class PartsInventory(db.Model):
    __tablename__ = 'parts_inventory'
    id               = db.Column(db.Integer,    primary_key=True)
    part_name        = db.Column(db.String(255), nullable=False)
    price            = db.Column(db.Float,       nullable=False)
    car_model        = db.Column(db.String(255), nullable=False)
    quotation_number = db.Column(db.String(100), nullable=False)
    quotation_date   = db.Column(db.Date,        nullable=False)
    created_at       = db.Column(db.DateTime,    default=datetime.utcnow)

# Create tables if they don't exist
with app.app_context():
    db.create_all()

# ── Auth helpers ──────────────────────────────────────────────────────────────
PASSWORD = 'cmech4480'

def logged_in():
    return session.get('authenticated') is True

# ── Routes ────────────────────────────────────────────────────────────────────

@app.route('/', methods=['GET', 'POST'])
def login():
    if logged_in():
        return redirect(url_for('upload'))
    if request.method == 'POST':
        if request.form.get('password') == PASSWORD:
            session['authenticated'] = True
            return redirect(url_for('upload'))
        flash('Incorrect password. Please try again.')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/upload', methods=['GET', 'POST'])
def upload():
    if not logged_in():
        return redirect(url_for('login'))

    if request.method == 'POST':
        car_model        = request.form.get('car_model', '').strip()
        quotation_number = request.form.get('quotation_number', '').strip()
        quotation_date_s = request.form.get('quotation_date', '').strip()
        file             = request.files.get('excel_file')

        # ── Validate form fields ──
        if not car_model or not quotation_number or not quotation_date_s:
            flash('Please fill in all fields (Car Model, Quotation Number, Date).')
            return redirect(url_for('upload'))

        if not file or file.filename == '':
            flash('Please select an Excel file to upload.')
            return redirect(url_for('upload'))

        try:
            quotation_date = datetime.strptime(quotation_date_s, '%Y-%m-%d').date()
        except ValueError:
            flash('Invalid date format.')
            return redirect(url_for('upload'))

        # ── Read Excel ──
        try:
            df = pd.read_excel(file)
        except Exception as e:
            flash(f'Could not read the Excel file: {e}')
            return redirect(url_for('upload'))

        # Normalise column names → lowercase, stripped
        df.columns = [c.strip().lower() for c in df.columns]
        print(f'[DEBUG] Columns found in uploaded file: {list(df.columns)}')

        if 'parts' not in df.columns or 'price' not in df.columns:
            flash(
                f'Excel must contain "Parts" and "Price" columns. '
                f'Found: {list(df.columns)}'
            )
            return redirect(url_for('upload'))

        # ── Drop rows where parts or price are empty ──
        df = df[['parts', 'price']].dropna(subset=['parts', 'price'])

        if df.empty:
            flash('No valid rows found in the Excel file.')
            return redirect(url_for('upload'))

        # ── Insert rows ──
        inserted = 0
        errors   = []
        for _, row in df.iterrows():
            try:
                entry = PartsInventory(
                    part_name        = str(row['parts']).strip(),
                    price            = float(row['price']),
                    car_model        = car_model,
                    quotation_number = quotation_number,
                    quotation_date   = quotation_date,
                )
                db.session.add(entry)
                inserted += 1
            except Exception as e:
                errors.append(str(e))

        db.session.commit()

        if errors:
            flash(f'Uploaded {inserted} parts with {len(errors)} row error(s): {errors[0]}')
        else:
            flash(f'Successfully saved {inserted} parts for {car_model} — Quotation {quotation_number}.', 'success')

        return redirect(url_for('upload'))

    # GET
    return render_template('upload.html')


@app.route('/models')
def models():
    if not logged_in():
        return redirect(url_for('login'))

    # Distinct car models + count of unique quotations + total parts stored
    rows = (
        db.session.query(
            PartsInventory.car_model,
            db.func.count(db.distinct(PartsInventory.quotation_number)).label('quotation_count'),
            db.func.count(PartsInventory.id).label('parts_count'),
            db.func.max(PartsInventory.quotation_date).label('latest_date'),
        )
        .group_by(PartsInventory.car_model)
        .order_by(PartsInventory.car_model)
        .all()
    )
    return render_template('models.html', models=rows)


@app.route('/search')
def search():
    if not logged_in():
        return redirect(url_for('login'))

    car_model  = request.args.get('car_model',  '').strip()
    part_name  = request.args.get('part_name',  '').strip()
    quote_no   = request.args.get('quote_no',   '').strip()

    query = PartsInventory.query

    if car_model:
        query = query.filter(PartsInventory.car_model.ilike(f'%{car_model}%'))
    if part_name:
        query = query.filter(PartsInventory.part_name.ilike(f'%{part_name}%'))
    if quote_no:
        query = query.filter(PartsInventory.quotation_number.ilike(f'%{quote_no}%'))

    results = query.order_by(
        PartsInventory.car_model,
        PartsInventory.quotation_date.desc(),
        PartsInventory.part_name
    ).all()

    # Distinct car models for the dropdown
    all_models = [
        r[0] for r in
        db.session.query(PartsInventory.car_model).distinct().order_by(PartsInventory.car_model).all()
    ]

    return render_template(
        'search.html',
        results=results,
        all_models=all_models,
        car_model=car_model,
        part_name=part_name,
        quote_no=quote_no,
    )

@app.route('/run-migration')
def run_migration():
    try:
        db.session.execute(db.text("""
            ALTER TABLE parts_inventory 
            ADD COLUMN IF NOT EXISTS quotation_date DATE;
        """))
        db.session.execute(db.text("""
            ALTER TABLE parts_inventory 
            ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW();
        """))
        db.session.execute(db.text("""
            UPDATE parts_inventory 
            SET quotation_date = CURRENT_DATE 
            WHERE quotation_date IS NULL;
        """))
        db.session.commit()
        return "Migration successful! Columns added. You can delete this route now."
    except Exception as e:
        db.session.rollback()
        return f"Error: {e}"
    
if __name__ == '__main__':
    app.run(debug=True)
