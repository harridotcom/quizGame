from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
import os
from dotenv import load_dotenv
import json
import uuid
from typing import Dict, List, Optional, Set, Any
import time
import random
import string

load_dotenv()  # Load environment variables from a .env file

app = FastAPI()

# Setup CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # adjust this in production!
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Constants
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
QUESTIONS_FILE = "quiz_data.json"

# Custom JSON encoder to handle sets
class SetEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, set):
            return list(obj)
        return json.JSONEncoder.default(self, obj)

# In-memory database for rooms and users
rooms: Dict[str, dict] = {}
users: Dict[str, dict] = {}

# Load existing data from JSON file if it exists
try:
    with open(QUESTIONS_FILE, "r") as f:
        data = json.load(f)
        rooms = data.get("rooms", {})
        users = data.get("users", {})
        
        # Convert lists back to sets for answered_correctly
        for room_id, room_data in rooms.items():
            if "answered_correctly" in room_data:
                for username, answered_list in room_data["answered_correctly"].items():
                    room_data["answered_correctly"][username] = set(answered_list)
except (FileNotFoundError, json.JSONDecodeError):
    pass

def save_data():
    """Save data to JSON file"""
    # Create a deep copy to avoid modifying the original data
    data_to_save = {
        "rooms": {room_id: room_data.copy() for room_id, room_data in rooms.items()},
        "users": users.copy()
    }
    
    # Convert sets to lists for JSON serialization
    for room_id, room_data in data_to_save["rooms"].items():
        if "answered_correctly" in room_data:
            room_data["answered_correctly"] = {
                username: list(answered_set) 
                for username, answered_set in room_data["answered_correctly"].items()
            }
    
    with open(QUESTIONS_FILE, "w") as f:
        json.dump(data_to_save, f, cls=SetEncoder)

class RoomCreate(BaseModel):
    name: str
    topic: str
    max_players: Optional[int] = 10
    rounds: Optional[int] = 5

class UserCreate(BaseModel):
    username: str

class AnswerSubmit(BaseModel):
    room_id: str
    user_id: str
    question_id: str
    answer: str

class ScoreUpdate(BaseModel):
    room_id: str
    user_id: str
    points: int = 1

class StartQuiz(BaseModel):
    room_id: str
    admin_id: str

# Generate a random room code of specified length
def generate_room_code(length=5):
    """Generate a random room code of specified length"""
    # Use uppercase letters and numbers but exclude confusing characters like O, 0, I, 1
    characters = ''.join(set(string.ascii_uppercase + string.digits) - set('O0I1'))
    return ''.join(random.choice(characters) for _ in range(length))

@app.post("/create-room")
async def create_room(room: RoomCreate, request: Request):
    """Create a new quiz room with generated questions and short room code"""
    # Generate a short room code instead of UUID
    room_code = generate_room_code(5)
    
    # Make sure the code is unique
    while room_code in rooms:
        room_code = generate_room_code(5)
    
    if any(r["name"] == room.name for r in rooms.values()):
        raise HTTPException(status_code=400, detail="Room name already exists")
    
    # Generate questions using OpenRouter API
    questions = await generate_questions(room.topic, room.rounds)
    
    # Debug print to see what questions were generated
    print(f"Generated {len(questions)} questions for room {room_code}")
    if questions:
        print(f"First question sample: {questions[0]}")
    
    # Create admin user
    admin_id = str(uuid.uuid4())
    admin_username = f"Admin-{room_code[:3]}"
    
    users[admin_id] = {
        "id": admin_id,
        "username": admin_username,
        "current_room": room_code,
        "score": 0,
        "is_admin": True,
        "joined_at": time.time()
    }
    
    # Create the room
    rooms[room_code] = {
        "id": room_code,
        "name": room.name,
        "topic": room.topic,
        "max_players": room.max_players,
        "questions": questions,
        "players": [admin_username],
        "admin_id": admin_id,
        "current_question": 0,
        "scores": {admin_username: 0},
        "started": False,
        "created_at": time.time(),
        # Initialize answered_correctly as a dict of username to empty set
        "answered_correctly": {admin_username: set()}
    }
    
    save_data()
    
    return {
        "message": f"Room '{room.name}' created successfully. You are the admin.",
        "room_id": room_code,
        "admin_id": admin_id,
        "admin_username": admin_username,
        "topic": room.topic,
        "questions_count": len(questions)
    }

@app.post("/join-room/{room_id}")
async def join_room(room_id: str, user: UserCreate):
    """Join an existing quiz room"""
    if room_id not in rooms:
        raise HTTPException(status_code=404, detail="Room not found")
    
    room = rooms[room_id]
    
    # Debug print to see what's in the room
    print(f"Room data: {json.dumps({k: v for k, v in room.items() if k != 'questions'}, cls=SetEncoder)}")
    print(f"Questions count: {len(room.get('questions', []))}")
    if 'questions' in room and len(room['questions']) > 0:
        print(f"First question sample: {room['questions'][0]}")
    
    if len(room["players"]) >= room["max_players"]:
        raise HTTPException(status_code=400, detail="Room is full")
    
    # Check if username is already taken in this room
    if user.username in room["players"]:
        # Check if the user already exists
        existing_user_id = None
        for uid, u in users.items():
            if u.get("username") == user.username and u.get("current_room") == room_id:
                existing_user_id = uid
                break
        
        if existing_user_id:
            # Return the existing user info
            user_info = users[existing_user_id]
            
            # Make sure we have questions to return
            questions_to_return = []
            if 'questions' in room and isinstance(room['questions'], list):
                questions_to_return = [
                    {
                        "question_id": q.get("id", ""),
                        "text": q.get("text", ""),
                        "options": q.get("options", [])
                    } for q in room["questions"]
                ]
            
            is_admin = user_info.get("is_admin", False)
            
            return {
                "message": f"User '{user.username}' already in room '{room['name']}'.",
                "user_id": existing_user_id,
                "is_admin": is_admin,
                "players": room["players"],
                "questions": questions_to_return,
                "room_status": {
                    "started": room["started"],
                    "current_question": room["current_question"],
                    "total_questions": len(room.get("questions", [])),
                    "waiting_for_admin": not room["started"]
                },
                "leaderboard": sorted(room["scores"].items(), key=lambda x: x[1], reverse=True)
            }
        else:
            raise HTTPException(status_code=400, detail="Username already taken in this room")
    
    # Create or update user
    user_id = str(uuid.uuid4())
    users[user_id] = {
        "id": user_id,
        "username": user.username,
        "current_room": room_id,
        "score": 0,
        "is_admin": False,  # Normal user, not admin
        "joined_at": time.time()
    }
    
    # Add user to room
    room["players"].append(user.username)
    room["scores"][user.username] = 0
    
    # Initialize answered_correctly tracking for this user
    if "answered_correctly" not in room:
        room["answered_correctly"] = {}
    room["answered_correctly"][user.username] = set()
    
    save_data()
    
    # Ensure we have questions to return
    questions_to_return = []
    if 'questions' in room and isinstance(room['questions'], list):
        questions_to_return = [
            {
                "question_id": q.get("id", ""),
                "text": q.get("text", ""),
                "options": q.get("options", [])
            } for q in room["questions"]
        ]
    else:
        # If no questions exist, let's log this
        print(f"WARNING: No questions found for room {room_id}")
    
    # Return room info including questions but without correct answers
    return {
        "message": f"User '{user.username}' joined room '{room['name']}'.",
        "user_id": user_id,
        "is_admin": False,
        "players": room["players"],
        "questions": questions_to_return,
        "room_status": {
            "started": room["started"],
            "current_question": room["current_question"],
            "total_questions": len(room.get("questions", [])),
            "waiting_for_admin": not room["started"]
        },
        "leaderboard": sorted(room["scores"].items(), key=lambda x: x[1], reverse=True)
    }

@app.post("/start-quiz")
async def start_quiz(start: StartQuiz):
    """Start the quiz (admin only)"""
    if start.room_id not in rooms:
        raise HTTPException(status_code=404, detail="Room not found")
    
    room = rooms[start.room_id]
    
    # Check if the user is the admin
    if room.get("admin_id") != start.admin_id:
        raise HTTPException(status_code=403, detail="Only the admin can start the quiz")
    
    # Start the quiz
    room["started"] = True
    save_data()
    
    return {
        "message": "Quiz started successfully!",
        "room_id": start.room_id,
        "started": True,
        "players_count": len(room["players"])
    }

@app.get("/room-status/{room_id}")
async def get_room_status(room_id: str):
    """Get current status of a room"""
    if room_id not in rooms:
        raise HTTPException(status_code=404, detail="Room not found")
    
    room = rooms[room_id]
    return {
        "name": room["name"],
        "topic": room["topic"],
        "players": room["players"],
        "current_question": room["current_question"],
        "total_questions": len(room["questions"]),
        "scores": room["scores"],
        "started": room["started"],
        "admin_id": room["admin_id"],
        "waiting_for_admin": not room["started"],
        "leaderboard": sorted(room["scores"].items(), key=lambda x: x[1], reverse=True)
    }

@app.post("/update-score")
async def update_score(score_update: ScoreUpdate):
    """Update a user's score and return the updated leaderboard"""
    if score_update.room_id not in rooms:
        raise HTTPException(status_code=404, detail="Room not found")
    
    if score_update.user_id not in users:
        raise HTTPException(status_code=404, detail="User not found")
    
    room = rooms[score_update.room_id]
    user = users[score_update.user_id]
    
    # Update user score
    user_name = user["username"]
    room["scores"][user_name] = room["scores"].get(user_name, 0) + score_update.points
    user["score"] += score_update.points
    
    save_data()
    
    return {
        "username": user_name,
        "new_score": room["scores"][user_name],
        "leaderboard": sorted(room["scores"].items(), key=lambda x: x[1], reverse=True)
    }

@app.post("/submit-answer")
async def submit_answer(answer: AnswerSubmit):
    """Submit an answer to a question and automatically update score if correct"""
    if answer.room_id not in rooms:
        raise HTTPException(status_code=404, detail="Room not found")
    
    if answer.user_id not in users:
        raise HTTPException(status_code=404, detail="User not found")
    
    room = rooms[answer.room_id]
    user = users[answer.user_id]
    user_name = user["username"]
    
    if not room["started"]:
        raise HTTPException(status_code=400, detail="Quiz hasn't started yet. Waiting for admin to start.")
    
    # Find the question
    question = next((q for q in room["questions"] if q["id"] == answer.question_id), None)
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")
    
    # Ensure we have a set to track answered questions
    if "answered_correctly" not in room:
        room["answered_correctly"] = {}
    if user_name not in room["answered_correctly"]:
        room["answered_correctly"][user_name] = set()
    
    # Check if user already answered this question correctly
    already_answered = answer.question_id in room["answered_correctly"][user_name]
    if already_answered:
        return {
            "correct": False,
            "already_answered": True,
            "message": "You've already answered this question correctly.",
            "current_score": room["scores"][user_name],
            "leaderboard": sorted(room["scores"].items(), key=lambda x: x[1], reverse=True)
        }
    
    # Check if answer is correct
    is_correct = answer.answer.lower() == question["correct_answer"].lower()
    
    # Automatically update score if correct
    if is_correct:
        # Add 1 point to the user's score
        room["scores"][user_name] = room["scores"].get(user_name, 0) + 1
        user["score"] += 1
        
        # Mark question as correctly answered by this user
        room["answered_correctly"][user_name].add(answer.question_id)
    
    save_data()
    
    return {
        "correct": is_correct,
        "correct_answer": question["correct_answer"],
        "points_earned": 1 if is_correct else 0,
        "current_score": room["scores"][user_name],
        "leaderboard": sorted(room["scores"].items(), key=lambda x: x[1], reverse=True)
    }

@app.get("/leaderboard/{room_id}")
async def get_leaderboard(room_id: str):
    """Get the current leaderboard for a room"""
    if room_id not in rooms:
        raise HTTPException(status_code=404, detail="Room not found")
    
    room = rooms[room_id]
    
    return {
        "room_name": room["name"],
        "leaderboard": sorted(room["scores"].items(), key=lambda x: x[1], reverse=True)
    }

async def generate_questions(topic: str, count: int = 5) -> List[dict]:
    """Generate quiz questions using OpenRouter API"""
    prompt = f""" 
    Generate 5 quiz questions on random twitter tweets in india, the latest trends in India are the following select any and generate questions based on that:
    	user has entered topic {topic} so please generate questions based on that also
#SongkranCTWxFB
#Coachella2025
#AprilFoolsDay
#LISACHELLA
#Perfect10LinersFinalEP
#ElonMusk
#ENCHELLA, 
#PahalgamTerroristAttack,#ENHYPEN, #NintendoSwitch2, #englot, #goodbadugly, #JENCHELLA, #4ป่าช้าแตก, #MGIxFaye1stFanMeeting, #earthquake, #Riyadh, #Pahalgam, #ค่าไฟแพง, #deprem, #JENCHELLA2025
    . Format as JSON array with:
    - id (string)
    - text (question)
    - options (array of 4 strings)
    - correct_answer (string)
    """
    
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": "openai/gpt-3.5-turbo",
        "messages": [
            {"role": "system", "content": "You are a helpful quiz generator that always outputs valid JSON."},
            {"role": "user", "content": prompt}
        ],
        "response_format": {"type": "json_object"}
    }
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=30.0
            )
            
            response.raise_for_status()
            result = response.json()
            
            # Extract the JSON content
            content = result["choices"][0]["message"]["content"]
            content_data = json.loads(content)
            
            # Ensure we have a list of questions
            if isinstance(content_data, dict):
                questions = content_data.get("questions", [])
            else:
                questions = content_data if isinstance(content_data, list) else []
            
            # Add IDs if missing
            for i, q in enumerate(questions):
                q["id"] = q.get("id", str(uuid.uuid4()))
                
            # If no questions were generated or parsed, use fallback
            if not questions:
                print("WARNING: No questions generated, using fallback questions")
                questions = [
                    {
                        "id": str(uuid.uuid4()),
                        "text": f"Question 1 about {topic}?",
                        "options": ["Option A", "Option B", "Option C", "Option D"],
                        "correct_answer": "Option A"
                    },
                    {
                        "id": str(uuid.uuid4()),
                        "text": f"Question 2 about {topic}?",
                        "options": ["Option A", "Option B", "Option C", "Option D"],
                        "correct_answer": "Option B"
                    }
                ]
            
            return questions[:count]  # Return only requested number
            
    except Exception as e:
        print(f"Error generating questions: {str(e)}")
        # Fallback to test questions with more detailed fallback
        return [
            {
                "id": str(uuid.uuid4()),
                "text": f"Which platform introduced Stories first?",
                "options": ["Facebook", "Instagram", "Snapchat", "Twitter"],
                "correct_answer": "Snapchat"
            },
            {
                "id": str(uuid.uuid4()),
                "text": f"Which social media platform is known for its 280-character limit?",
                "options": ["Facebook", "Instagram", "Snapchat", "Twitter"],
                "correct_answer": "Twitter"
            }
        ]

@app.on_event("shutdown")
def shutdown_event():
    """Save data when the application shuts down"""
    save_data()