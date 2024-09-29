from flask import (
    Flask, request, render_template, Blueprint, send_file, 
    make_response, jsonify, abort, url_for
)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import and_, or_, not_, create_engine, text
import requests
from urllib.parse import quote_plus, unquote
import json
import os
from dotenv import load_dotenv
import io
from PIL import Image, ImageDraw, ImageFont
import logging
import textwrap
import barcode
from barcode.writer import ImageWriter
import pandas as pd
import threading
import schedule
import time
import re

# Define the Google Sheet URL variable
GOOGLE_SHEET_URL = "https://docs.google.com/spreadsheets/d/1po70GCN9JUwrWgycMueNfxpEvBjLd7DQkiMRUQFFsL8/export?format=csv&gid=0"

# Define the SQLite database engine
engine = create_engine('sqlite:///instance/db.masterlist.sqlite3')

# Read the Google Sheet into a Pandas DataFrame
def read_google_sheet():
    try:
        df = pd.read_csv(GOOGLE_SHEET_URL)
        return df
    except Exception as e:
        print(f"Error reading Google Sheet: {e}")
        return None

# Update the SQLite database with any new data from gsheet dataframe
def update_sqlite_database(df):
    if df is not None:
        try:
            # Count rows before update
            with engine.connect() as conn:
                result = conn.execute(text("SELECT COUNT(*) FROM movie"))
                row_count_before = result.scalar()

            # Update the database
            df.to_sql('movie', engine, if_exists='replace', index=False)

            # Count rows after update
            with engine.connect() as conn:
                result = conn.execute(text("SELECT COUNT(*) FROM movie"))
                row_count_after = result.scalar()

            rows_updated = row_count_after - row_count_before
            print(f"Database updated successfully. Total rows updated: {rows_updated}")
        except Exception as e:
            print(f"Error updating database: {e}")
        finally:
            del df
    else:
        print("No DataFrame to update the database.")

DB_LOCK_FILE = "/tmp/update_database.lock"

# Function to read Google Sheet and update the SQLite database
def update_database():
    if os.path.exists(DB_LOCK_FILE):
        print("Database update already in progress. Skipping.")
        return
    
    try:
        with open(DB_LOCK_FILE, "w") as lock:
            lock.write(str(os.getpid()))
        df = read_google_sheet()
        update_sqlite_database(df)
        # logging.basicConfig(level=logging.DEBUG)
    
    finally:
        if os.path.exists(DB_LOCK_FILE):
            os.remove(DB_LOCK_FILE)

# Function to run the update_database function at 08:00 system time (which would be 04:00 ET)
def schedule_updates():
    schedule.every().day.at("08:00").do(update_database)
    while True:
        schedule.run_pending()
        time.sleep(1)

# Start the scheduler in a separate thread
scheduler_thread = threading.Thread(target=schedule_updates)
scheduler_thread.daemon = True
scheduler_thread.start()

# Initial update at application startup
update_database()

# Load environment variables
load_dotenv()

db = SQLAlchemy()

class Movie(db.Model):
    ID = db.Column(db.Integer, primary_key=True)
    TITLE = db.Column(db.String(125), nullable=False)
    UPC = db.Column(db.String(125), nullable=False)
    QUALITY = db.Column(db.String(10), nullable=False)
    YEAR = db.Column(db.Integer, nullable=False)
    MA = db.Column(db.String(10), nullable=False)
    NOTES = db.Column(db.String(60), nullable=False)

main = Blueprint("main", __name__)

def check_referrer():
    referrer = request.headers.get('Referer')
    allowed_domains = [
    #'http://localhost:5000', # comment for deployment
    #'http://192.168.1.31:5000', # comment for deployment
    'https://my-upc.com', 
    'https://www.my-upc.com',
    'https://my-upc.fly.dev'
    ]
    if not referrer or not any(referrer.startswith(domain) for domain in allowed_domains):
        abort(403)

@main.route("/")
def index():
    return render_template("index.html")

@main.route("/search")
def search():
    check_referrer()
    q = request.args.get("q")
    page = request.args.get('page', 1, type=int)
    per_page = 25  # Adjust this number as needed
    print(q)

    if q and len(q) >= 2:
        # Create a list of filter conditions
        conditions = []

        # Handle UPC search separately
        if len(q) == 12 and q.isdigit():
            conditions.append(Movie.UPC == q)
        else:
            # Split the search query into individual words for non-UPC searches
            search_terms = q.lower().split()
            for term in search_terms:
                term_condition = or_(
                    Movie.QUALITY.icontains(term),
                    Movie.TITLE.icontains(term),
                    Movie.YEAR.icontains(term),
                    and_(
                        Movie.NOTES.icontains(term),
                        not_(Movie.NOTES.icontains("blu")),
                        not_(Movie.NOTES.icontains("dvd"))
                    )
                )
                conditions.append(term_condition)

        # Combine all conditions with AND
        results = (Movie.query
           .filter(and_(*conditions))
           .order_by(Movie.TITLE.asc(), Movie.YEAR.desc())
           .with_entities(
               Movie.TITLE.label('title'),
               Movie.UPC.label('upc'),
               Movie.QUALITY.label('quality'),
               Movie.YEAR.label('year'),
               Movie.MA.label('ma'),
               Movie.NOTES.label('notes')
           )
           .paginate(page=page, per_page=per_page, error_out=False))
    else:
        results = []

    return render_template("search_results.html", results=results)

@main.route("/barcode/<upc>")
def generate_barcode(upc):
    check_referrer()
    try:
        # Check if the UPC is a string of the correct length
        if not isinstance(upc, str) or len(upc) != 12:
            return "Invalid UPC", 400

        barcode_class = barcode.get_barcode_class('upc')
        upc_barcode = barcode_class(upc, writer=ImageWriter())
        buffer = io.BytesIO()
        upc_barcode.write(buffer)
        buffer.seek(0)

        barcode_response = make_response(send_file(buffer, mimetype='image/png'))
        
        # Set cache control headers
        barcode_response.headers['Cache-Control'] = 'public, max-age=2592000'  # Cache for 30 days
        barcode_response.headers['ETag'] = upc  # Use UPC as ETag
        
        return barcode_response
    except Exception as e:
        # Log the error and return a 500 error
        print(f"Error generating barcode: {e}")
        return "Internal server error", 500

def generate_placeholder(text, size=(300, 450)):
    #logging.debug(f"Generating placeholder for text: {text}")
    img = Image.new('RGB', size, color='lightgray')
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)  # Increased font size
    
    # Remove '+' signs and decode URL-encoded characters
    decoded_text = unquote(text).replace('+', ' ')
    #logging.debug(f"Decoded text: {decoded_text}")
    
    # Wrap text
    max_width = size[0] - 40  # Increased margin
    lines = textwrap.wrap(decoded_text, width=18)  # Adjusted width for larger font
    
    # Calculate total text height
    line_height = font.getbbox('hg')[3] - font.getbbox('hg')[1]
    total_text_height = line_height * len(lines)
    
    # Calculate starting y position to center text vertically
    y = (size[1] - total_text_height) // 2
    
    for line in lines:
        # Center each line horizontally
        bbox = font.getbbox(line)
        line_width = bbox[2] - bbox[0]
        x = (size[0] - line_width) // 2
        d.text((x, y), line, font=font, fill='black')
        y += line_height
    
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='PNG')
    img_byte_arr.seek(0)
    
    #logging.debug("Placeholder generated successfully")
    return img_byte_arr

@main.route("/placeholder/<text>")
def placeholder(text):
    check_referrer()
    #logging.debug(f"Placeholder route called with text: {text}")
    try:
        img_buffer = generate_placeholder(text[:100])  # Limit text length
        img_buffer.seek(0)
        placeholder_response = make_response(send_file(img_buffer, mimetype='image/png'))
        placeholder_response.headers['Cache-Control'] = 'public, max-age=86400'  # Cache for 24 hours
        return placeholder_response
    except Exception as e:
        logging.error(f"Error in placeholder: {str(e)}")
        return "Error generating placeholder", 500

@main.route("/movie_image/<title>")
def get_movie_image(title):
    check_referrer()
    #logging.debug(f"get_movie_image called with title: {title}")
    year = request.args.get('year')
    try:
        # Your existing OMDB API logic here
        api_key = os.getenv('OMDB_API_KEY')
        if not api_key:
            raise ValueError("OMDB API key not found in environment variables")

        # Extract year if present in the title
        if '(' in title and ')' in title:
            year_in_title = title.split('(')[-1].split(')')[0]
            if year_in_title.isdigit() and len(year_in_title) == 4:
                year = int(year_in_title)
                simplified_title = title.split('(')[0].strip()
            else:
                if year:
                    year = int(year)
                simplified_title = title
        else:
            if year:
                year = int(year)
            simplified_title = title

        encoded_title = quote_plus(simplified_title)
        search_url = f"http://www.omdbapi.com/?s={encoded_title}&type=movie&apikey={api_key}"
        
        print(f"Searching for: {simplified_title} (Year: {year if year else 'Not specified'})")
        print(f"Search URL: {search_url}")
        
        search_response = requests.get(search_url)
        search_data = search_response.json()
        
        print(f"Search response: {json.dumps(search_data, indent=2)}")

        if search_data.get('Response') == 'True' and search_data.get('Search'):
            # Implement a scoring system
            best_match = None
            best_score = -1
            for movie in search_data['Search']:
                score = 0
                # Title similarity (case-insensitive)
                if movie['Title'].lower() == simplified_title.lower():
                    score += 3
                elif simplified_title.lower() in movie['Title'].lower():
                    score += 1

                # Year matching
                if year:
                    movie_year = int(movie['Year'].split('–')[0])  # Handle series with year ranges
                    if movie_year == int(year):
                        score += 2
                    elif abs(movie_year - int(year)) <= 1:  # Allow 1 year difference
                        score += 1

                if score > best_score:
                    best_score = score
                    best_match = movie

            if best_match:
                imdb_id = best_match['imdbID']

                # Now get the full movie details using the IMDb ID
                movie_url = f"http://www.omdbapi.com/?i={imdb_id}&apikey={api_key}"
                movie_response = requests.get(movie_url)
                movie_data = movie_response.json()

                print(f"Best match: {best_match['Title']} ({best_match['Year']}) with score {best_score}")
                print(f"Movie data: {json.dumps(movie_data, indent=2)}")

                poster_url = movie_data.get('Poster', '')
                if poster_url and poster_url != 'N/A':
                    print(f"Found poster URL: {poster_url}")
                    poster_response = make_response(jsonify({
                        "image_url": poster_url,
                        "imdb_id": imdb_id,
                        "movie_data": movie_data  # Include full movie data in the response
                    }))
                    poster_response.headers['Cache-Control'] = 'public, max-age=86400'  # Cache for 24 hours
                    return poster_response
                else:
                    print("No poster URL found or poster not available")
            else:
                print(f"No suitable match found for '{simplified_title}'")
            if 'Error' in search_data:
                print(f"API Error: {search_data['Error']}")
        
        # If no image found, return the URL for the placeholder image
        placeholder_url = url_for('main.placeholder', text=quote_plus(title[:100]), _external=True)
        #logging.debug(f"Returning placeholder URL: {placeholder_url}")
        return jsonify({"image_url": placeholder_url})
    except requests.RequestException as e:
        logging.error(f"Network error in get_movie_image: {str(e)}")
        placeholder_url = url_for('main.placeholder', text=quote_plus(title[:100]), _external=True)
        return jsonify({"error": "Network error", "image_url": placeholder_url}), 500
    except Exception as e:
        logging.error(f"Unexpected error in get_movie_image: {str(e)}")
        placeholder_url = url_for('main.placeholder', text=quote_plus(title[:100]), _external=True)
        return jsonify({"error": "Unexpected error", "image_url": placeholder_url}), 500

def create_app():
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///db.masterlist.sqlite3"

    db.init_app(app)

    app.register_blueprint(main)

    # For search_results.html to be able to use regex to filter for 12 digit upc's in the upc column data
    @app.template_filter('regex_findall')
    def regex_findall_filter(s, pattern):
        return re.findall(pattern, s)

    @app.template_filter('regex_replace')
    def regex_replace(s, find, replace):
        return re.sub(find, replace, s)

    return app
