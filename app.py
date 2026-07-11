from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User, Course, Lesson, Enrollment, Progress
from datetime import datetime
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///elearning.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Veuillez vous connecter pour accéder à cette page.'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def slugify(text):
    return text.lower().replace(' ', '-').replace("'", '-').replace('é', 'e').replace('è', 'e').replace('ê', 'e').replace('à', 'a').replace('ù', 'u').replace('ç', 'c')

@app.context_processor
def inject_now():
    categories = db.session.query(Course.category).filter(Course.is_published == True).distinct().all()
    return {'now': datetime.utcnow(), 'categories': [c[0] for c in categories if c[0]]}

@app.route('/')
def index():
    featured = Course.query.filter_by(is_published=True).order_by(Course.created_at.desc()).limit(6).all()
    return render_template('index.html', courses=featured)

@app.route('/cours')
def courses():
    category = request.args.get('category')
    level = request.args.get('level')
    search = request.args.get('search')
    query = Course.query.filter_by(is_published=True)
    if category:
        query = query.filter_by(category=category)
    if level:
        query = query.filter_by(level=level)
    if search:
        query = query.filter(Course.title.contains(search) | Course.description.contains(search))
    courses = query.order_by(Course.created_at.desc()).all()
    return render_template('courses.html', courses=courses)

@app.route('/cours/<slug>')
def course_detail(slug):
    course = Course.query.filter_by(slug=slug).first_or_404()
    enrolled = False
    if current_user.is_authenticated:
        enrolled = Enrollment.query.filter_by(user_id=current_user.id, course_id=course.id).first() is not None
    return render_template('course_detail.html', course=course, enrolled=enrolled)

@app.route('/cours/<slug>/lecon/<lesson_slug>')
@login_required
def lesson_view(slug, lesson_slug):
    course = Course.query.filter_by(slug=slug).first_or_404()
    lesson = Lesson.query.filter_by(slug=lesson_slug, course_id=course.id).first_or_404()
    enrollment = Enrollment.query.filter_by(user_id=current_user.id, course_id=course.id).first()
    if not enrollment and not lesson.is_free:
        flash('Vous devez être inscrit à ce cours pour accéder à cette leçon.', 'warning')
        return redirect(url_for('course_detail', slug=course.slug))
    prev_lesson = Lesson.query.filter(Lesson.course_id == course.id, Lesson.order < lesson.order).order_by(Lesson.order.desc()).first()
    next_lesson = Lesson.query.filter(Lesson.course_id == course.id, Lesson.order > lesson.order).order_by(Lesson.order.asc()).first()
    progress = Progress.query.filter_by(user_id=current_user.id, lesson_id=lesson.id).first()
    return render_template('lesson.html', course=course, lesson=lesson, prev=prev_lesson, next=next_lesson, progress=progress)

@app.route('/api/lecon/<int:lesson_id>/complete', methods=['POST'])
@login_required
def complete_lesson(lesson_id):
    lesson = Lesson.query.get_or_404(lesson_id)
    enrollment = Enrollment.query.filter_by(user_id=current_user.id, course_id=lesson.course_id).first()
    if not enrollment:
        return jsonify({'error': 'Non inscrit'}), 403
    progress = Progress.query.filter_by(user_id=current_user.id, lesson_id=lesson_id).first()
    if not progress:
        progress = Progress(user_id=current_user.id, lesson_id=lesson_id, completed=True, completed_at=datetime.utcnow())
        db.session.add(progress)
    else:
        progress.completed = True
        progress.completed_at = datetime.utcnow()
    total = Lesson.query.filter_by(course_id=lesson.course_id).count()
    done = Progress.query.filter_by(user_id=current_user.id, completed=True).join(Lesson).filter(Lesson.course_id == lesson.course_id).count()
    if done >= total:
        enrollment.completed = True
    db.session.commit()
    return jsonify({'success': True, 'progress': f'{done}/{total}'})

@app.route('/sinscrire/<int:course_id>')
@login_required
def enroll(course_id):
    course = Course.query.get_or_404(course_id)
    existing = Enrollment.query.filter_by(user_id=current_user.id, course_id=course_id).first()
    if not existing:
        enrollment = Enrollment(user_id=current_user.id, course_id=course_id)
        db.session.add(enrollment)
        db.session.commit()
        flash(f'Inscription réussie au cours "{course.title}" !', 'success')
    else:
        flash('Vous êtes déjà inscrit à ce cours.', 'info')
    return redirect(url_for('course_detail', slug=course.slug))

@app.route('/dashboard')
@login_required
def dashboard():
    enrollments = Enrollment.query.filter_by(user_id=current_user.id).all()
    return render_template('dashboard.html', enrollments=enrollments)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm = request.form.get('confirm_password')
        if User.query.filter_by(username=username).first():
            flash('Ce nom d\'utilisateur existe déjà.', 'danger')
            return render_template('register.html')
        if User.query.filter_by(email=email).first():
            flash('Cet email est déjà utilisé.', 'danger')
            return render_template('register.html')
        if password != confirm:
            flash('Les mots de passe ne correspondent pas.', 'danger')
            return render_template('register.html')
        if len(password) < 6:
            flash('Le mot de passe doit faire au moins 6 caractères.', 'danger')
            return render_template('register.html')
        user = User(username=username, email=email, password_hash=generate_password_hash(password))
        db.session.add(user)
        db.session.commit()
        login_user(user)
        flash('Compte créé avec succès !', 'success')
        return redirect(url_for('dashboard'))
    return render_template('register.html')

@app.route('/connexion', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            next_page = request.args.get('next')
            flash('Connecté avec succès !', 'success')
            return redirect(next_page or url_for('dashboard'))
        flash('Nom d\'utilisateur ou mot de passe incorrect.', 'danger')
    return render_template('login.html')

@app.route('/deconnexion')
@login_required
def logout():
    logout_user()
    flash('Déconnecté avec succès.', 'info')
    return redirect(url_for('index'))

@app.route('/admin')
@login_required
def admin_dashboard():
    if not current_user.is_admin:
        flash('Accès réservé aux administrateurs.', 'danger')
        return redirect(url_for('dashboard'))
    courses = Course.query.order_by(Course.created_at.desc()).all()
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template('admin/dashboard.html', courses=courses, users=users)

@app.route('/admin/cours/ajouter', methods=['GET', 'POST'])
@login_required
def admin_course_add():
    if not current_user.is_admin:
        flash('Accès réservé aux administrateurs.', 'danger')
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        title = request.form.get('title')
        course = Course(
            title=title,
            slug=slugify(title),
            description=request.form.get('description'),
            short_description=request.form.get('short_description'),
            category=request.form.get('category'),
            level=request.form.get('level'),
            price=float(request.form.get('price', 0)),
            instructor=request.form.get('instructor', 'Formateur'),
            image_url=request.form.get('image_url', 'https://images.unsplash.com/photo-1516321318423-f06f85e504b3?w=800'),
            is_published=request.form.get('is_published') == 'on'
        )
        db.session.add(course)
        db.session.commit()
        flash('Cours créé avec succès !', 'success')
        return redirect(url_for('admin_dashboard'))
    return render_template('admin/course_form.html')

@app.route('/admin/cours/modifier/<int:course_id>', methods=['GET', 'POST'])
@login_required
def admin_course_edit(course_id):
    if not current_user.is_admin:
        flash('Accès réservé aux administrateurs.', 'danger')
        return redirect(url_for('dashboard'))
    course = Course.query.get_or_404(course_id)
    if request.method == 'POST':
        course.title = request.form.get('title')
        course.slug = slugify(request.form.get('title'))
        course.description = request.form.get('description')
        course.short_description = request.form.get('short_description')
        course.category = request.form.get('category')
        course.level = request.form.get('level')
        course.price = float(request.form.get('price', 0))
        course.instructor = request.form.get('instructor')
        course.image_url = request.form.get('image_url')
        course.is_published = request.form.get('is_published') == 'on'
        db.session.commit()
        flash('Cours mis à jour !', 'success')
        return redirect(url_for('admin_dashboard'))
    return render_template('admin/course_form.html', course=course)

@app.route('/admin/cours/supprimer/<int:course_id>')
@login_required
def admin_course_delete(course_id):
    if not current_user.is_admin:
        flash('Accès réservé aux administrateurs.', 'danger')
        return redirect(url_for('dashboard'))
    course = Course.query.get_or_404(course_id)
    db.session.delete(course)
    db.session.commit()
    flash('Cours supprimé.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/lecon/ajouter/<int:course_id>', methods=['GET', 'POST'])
@login_required
def admin_lesson_add(course_id):
    if not current_user.is_admin:
        flash('Accès réservé aux administrateurs.', 'danger')
        return redirect(url_for('dashboard'))
    course = Course.query.get_or_404(course_id)
    if request.method == 'POST':
        max_order = db.session.query(db.func.max(Lesson.order)).filter_by(course_id=course_id).scalar() or 0
        lesson = Lesson(
            course_id=course_id,
            title=request.form.get('title'),
            slug=slugify(request.form.get('title')),
            content=request.form.get('content'),
            video_url=request.form.get('video_url'),
            duration=request.form.get('duration', '00:00'),
            order=max_order + 1,
            is_free=request.form.get('is_free') == 'on'
        )
        db.session.add(lesson)
        db.session.commit()
        flash('Leçon ajoutée !', 'success')
        return redirect(url_for('admin_dashboard'))
    return render_template('admin/lesson_form.html', course=course)

@app.route('/admin/lecon/modifier/<int:lesson_id>', methods=['GET', 'POST'])
@login_required
def admin_lesson_edit(lesson_id):
    if not current_user.is_admin:
        flash('Accès réservé aux administrateurs.', 'danger')
        return redirect(url_for('dashboard'))
    lesson = Lesson.query.get_or_404(lesson_id)
    if request.method == 'POST':
        lesson.title = request.form.get('title')
        lesson.slug = slugify(request.form.get('title'))
        lesson.content = request.form.get('content')
        lesson.video_url = request.form.get('video_url')
        lesson.duration = request.form.get('duration')
        lesson.is_free = request.form.get('is_free') == 'on'
        db.session.commit()
        flash('Leçon mise à jour !', 'success')
        return redirect(url_for('admin_dashboard'))
    return render_template('admin/lesson_form.html', lesson=lesson, course=lesson.course)

@app.route('/admin/lecon/supprimer/<int:lesson_id>')
@login_required
def admin_lesson_delete(lesson_id):
    if not current_user.is_admin:
        flash('Accès réservé aux administrateurs.', 'danger')
        return redirect(url_for('dashboard'))
    lesson = Lesson.query.get_or_404(lesson_id)
    db.session.delete(lesson)
    db.session.commit()
    flash('Leçon supprimée.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/utilisateurs')
@login_required
def admin_users():
    if not current_user.is_admin:
        flash('Accès réservé aux administrateurs.', 'danger')
        return redirect(url_for('dashboard'))
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template('admin/users.html', users=users)

with app.app_context():
    db.create_all()
    if not User.query.filter_by(is_admin=True).first():
        admin = User(
            username='admin',
            email='mansourjemli@gmail.com',
            password_hash=generate_password_hash('admin123'),
            is_admin=True
        )
        db.session.add(admin)
        db.session.commit()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8000)
