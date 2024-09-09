from flask import Flask, request, render_template, Blueprint, send_file, make_response, jsonify, abort, url_for
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import and_, or_, not_
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
# Disabling rate limiting as will be putting behind CF
#from flask_limiter import Limiter
#from flask_limiter.util import get_remote_address

# Set up logging // commented for deployment
# logging.basicConfig(level=logging.DEBUG)

# Load environment variables
load_dotenv()

#limiter = Limiter(key_func=get_remote_address, default_limits=["100 per minute"])

db = SQLAlchemy()

class Movie(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    media = db.Column(db.String(10), nullable=False)
    upc = db.Column(db.String(12), nullable=False)
    title = db.Column(db.String(125), nullable=False)
    studio = db.Column(db.String(30), nullable=False)
    year = db.Column(db.Integer, nullable=False)
    genre = db.Column(db.String(30), nullable=False)
    rating = db.Column(db.String(6), nullable=False)
    notes = db.Column(db.String(30), nullable=False)

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
#@limiter.limit("100 per minute")
def index():
    #this might be causing issues with Cloudflare proxy
    #user_agent = request.headers.get('User-Agent')
    #if not user_agent or 'Mozilla' not in user_agent:
    #    abort(403)  # Forbidden
    return render_template("index.html")

@main.route("/search")
#@limiter.limit("100 per minute")
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
            conditions.append(Movie.upc == q)
        else:
            # Split the search query into individual words for non-UPC searches
            search_terms = q.lower().split()
            for term in search_terms:
                term_condition = or_(
                    Movie.media.icontains(term),
                    Movie.title.icontains(term),
                    Movie.studio.icontains(term),
                    Movie.year.icontains(term),
                    Movie.genre.icontains(term),
                    Movie.rating.icontains(term),
                    and_(
                        Movie.notes.icontains(term),
                        not_(Movie.notes.icontains("blu")),
                        not_(Movie.notes.icontains("dvd"))
                    )
                )
                conditions.append(term_condition)

        # Combine all conditions with AND
        results = Movie.query.filter(and_(*conditions)).order_by(Movie.title.asc(), Movie.year.desc()).paginate(page=page, per_page=per_page, error_out=False)
    else:
        results = []

    return render_template("search_results.html", results=results)

@main.route("/barcode/<upc>")
#@limiter.limit("60 per minute")
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
        barcode_response.headers['Cache-Control'] = 'public, max-age=31536000'  # Cache for 1 year
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
        placeholder_response.headers['Cache-Control'] = 'public, max-age=1209600'  # Cache for 14 days
        return placeholder_response
    except Exception as e:
        logging.error(f"Error in placeholder: {str(e)}")
        return "Error generating placeholder", 500

@main.route("/movie_image/<title>")
#@limiter.limit("20 per minute; 1600 per hour")
def get_movie_image(title):
    check_referrer()
    #logging.debug(f"get_movie_image called with title: {title}")
    try:
        # Your existing OMDB API logic here
        api_key = os.getenv('OMDB_API_KEY')
        if not api_key:
            raise ValueError("OMDB API key not found in environment variables")

        # Extract year if present in the title
        year = None
        if '(' in title and ')' in title:
            year = title.split('(')[-1].split(')')[0]
            if year.isdigit() and len(year) == 4:
                simplified_title = title.split('(')[0].strip()
            else:
                year = None
                simplified_title = title
        else:
            simplified_title = title

        encoded_title = quote_plus(simplified_title)
        search_url = f"http://www.omdbapi.com/?s={encoded_title}&type=movie&apikey={api_key}"
        
        print(f"Searching for: {simplified_title} (Year: {year if year else 'Not specified'})")
        print(f"Search URL: {search_url}")
        
        search_response = requests.get(search_url)
        search_data = search_response.json()
        
        print(f"Search response: {json.dumps(search_data, indent=2)}")
        
        if search_data.get('Response') == 'True' and search_data.get('Search'):
            # Find the best match considering the year if provided
            best_match = None
            for movie in search_data['Search']:
                if year and movie['Year'] == year:
                    best_match = movie
                    break
                elif not year and movie['Title'].lower() == simplified_title.lower():
                    best_match = movie
                    break
            
            if not best_match:
                best_match = search_data['Search'][0]  # Default to first result if no exact match

            imdb_id = best_match['imdbID']
            
            # Now get the full movie details using the IMDb ID
            movie_url = f"http://www.omdbapi.com/?i={imdb_id}&apikey={api_key}"
            movie_response = requests.get(movie_url)
            movie_data = movie_response.json()
            
            print(f"Movie data: {json.dumps(movie_data, indent=2)}")
            
            poster_url = movie_data.get('Poster', '')
            if poster_url and poster_url != 'N/A':
                print(f"Found poster URL: {poster_url}")
                poster_response = make_response(jsonify({
                    "image_url": poster_url,
                    "imdb_id": imdb_id,
                    "movie_data": movie_data  # Include full movie data in the response
                }))
                poster_response.headers['Cache-Control'] = 'public, max-age=7776000'  # Cache for 90 days
                return poster_response
            else:
                print("No poster URL found or poster not available")
        else:
            print(f"No results found for '{simplified_title}'")
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
    # Will put behind CF instead of onbox rate-limiting
    #limiter.init_app(app)  # Initialize limiter with the app

    app.register_blueprint(main)

    return app
