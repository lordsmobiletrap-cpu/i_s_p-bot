"""
Скрипт для заполнения банка вопросов IELTS Speaking Part 2.

Запуск:
    python seed_questions.py

Повторный запуск безопасен — дубликаты не добавляются.
Переменная окружения DB_PATH задаёт путь к БД (default: bot.db).
"""

import asyncio
from os import getenv

import aiosqlite
from dotenv import load_dotenv

load_dotenv()
DB_PATH = getenv("DB_PATH", "bot.db")

# ---------------------------------------------------------------------------
# Банк вопросов
# ---------------------------------------------------------------------------

QUESTIONS = [
    """Title: Describe an occasion when most people were smiling
You should say:
● what occasion it was
● where it was
● who were you with
● and explain why people were smiling.""",

    """Title: Describe your perfect job
You should say:
● What it is
● How you knew it
● What it is like
● And explain why you think it is perfect.""",

    """Title: Describe a family member whom you are proud of
You should say:
● who the family member is
● what the family member did
● and explain why you felt proud of the family member.""",

    """Title: Describe an occasion where you were not allowed to use a mobile phone
You should say:
● what you did
● when it was
● where it was
● why you were not allowed to use a mobile phone.""",

    """Title: Describe a person who makes plans a lot
You should say:
● Who he/she is
● How you knew him/her
● What plans he/she makes
● And explain how you feel about this person.""",

    """Title: Describe a piece of technology (not a phone) that you would like to own
You should say:
● What it is
● How much it costs
● What you will use it for
● And explain why you would like to own it.""",

    """Title: Describe a child you know who likes drawing very much
You should say:
● How you knew him/her
● What he/she is like
● How often he/she draws
● And explain why you think he/she likes drawing.""",

    """Title: Describe something that you can't live without (not a computer/phone)
You should say:
● What it is
● What you do with it
● How it helps you in your life
● And explain why you can't live without it.""",

    """Title: Describe a story (e.g. a fairy tale, etc.) you have read recently
You should say:
● What it is about
● When you read it
● Whether you liked it
● And explain what you have learned from it.""",

    """Title: Describe your favorite place in your house where you can relax
You should say:
● Where it is
● What it is like
● What you enjoy doing there
● And explain why you feel relaxed at this place.""",

    """Title: Describe a program or app on your computer or phone
You should say:
● What it is
● When/how you use it
● Where you found it
● And explain how you feel about it.""",

    """Title: Describe a time when you gave advice to others
You should say:
● When it was
● To whom you gave the advice
● What the advice was
● And explain why you gave the advice.""",

    """Title: Describe a movie you watched recently that you felt disappointed about
You should say:
● When it was
● Why you didn't like it
● Why you decided to watch it
● And explain why you felt disappointed about it.""",

    """Title: Describe a bike/motorbike/car trip you would like to have
You should say:
● where you would like to go
● how you would like to go there
● who you would like to go with
● and explain why you would like to go there by bike, motorbike or car.""",

    """Title: Describe a time you needed to use your imagination
You should say:
● When it was
● Why you needed to use imagination
● How difficult or easy it was
● And explain how you felt about it.""",

    """Title: Describe a quiet place you like to go
You should say:
● Where it is
● How you knew it
● How often you go there
● What you do there
● And explain how you feel about the place.""",

    """Title: Describe a movie you watched and enjoyed recently
You should say:
● When and where you watched it
● Who you watched it with
● What it was about
● And explain why you watched this movie.""",

    """Title: Describe an item on which you spent more than expected
You should say:
● What it is
● How much you spent on it
● Why you bought it
● And explain why you think you spent more than expected.""",

    """Title: Describe a person who solved a problem in a smart way
You should say:
● Who this person is
● What the problem was
● How he/she solved it
● And explain why you think he/she did it in a smart way.""",

    """Title: Describe a time when you encouraged someone to do something that
he/she didn't want to do
You should say:
● Who he or she is
● What you encouraged him/her to do
● How he/she reacted
● And explain why you encouraged him/her to do it.""",
# =========================================

    """Describe a book you read that you found useful
You should say:
● What it is
● When you read it
● Why you think it is useful
● And explain how you felt about it.""",

    """Describe an important thing that your family has kept for a long time
You should say:
What it is
How/when your family first got this thing
How long your family has kept it
And explain why this thing is important to your family.""",

    """Title: Describe an interesting building
You should say:
● where it is
● what it looks like
● why do you think it is unusual and interesting
● and explain why you would like to visit it.""",

    """Title: Describe an apology you made or received
You should say:
● when it happened
● who was involved
● why the apology was necessary
● and explain how you felt about it.""",

    """Title: Describe an area of science that you are interested in
You should say:
● what it is
● how you learned about it
● why you are interested in it
● and explain how it is useful in daily life.""",

    """Title: Describe a popular person
You should say:
● who this person is
● what kind of person he or she is
● when you see him/her normally
● and explain why you think this person is popular.""",

    """Title: Describe a creative person you admire
You should say:
● who the person is
● what kind of creativity they show
● how you know about them
● and explain why you admire them.""",

    """Title: Describe a book you have recently read
You should say:
● what kind of book it was
● what it was about
● what you learned from it
● and explain why you would or wouldn’t recommend it.""",

    """Title: Describe an interesting traditional story
You should say:
● what the story is about
● when/how you knew it
● who told you the story
● and explain how you felt when you first heard it.""",

    """Title: Describe a dinner you had with your friends or family
You should say:
● who you had dinner with
● where you had it
● what you ate
● and explain why it was special.""",

    """Title: Describe a time when the electricity was cut off
You should say:
● when it happened
● how long it lasted
● what you did during that time
● and explain how you felt about it.""",

    """Title: Describe an exciting activity you tried for the first time
You should say:
● what the activity was
● where and when you did it
● who you did it with
● and explain how you felt about it.""",

    """Title: Describe a friend of yours who likes to sing
You should say:
● who this friend is
● what kind of songs he/she sings
● how well he/she sings
● and explain how you feel when you hear this friend sing.""",

    """Title: Describe a time when you got lost
You should say:
● where you were
● how it happened
● what you did
● and explain how you felt about the situation.""",

    """Title: Describe a good friend who is important to you
You should say:
● who the person is
● how you met
● what you do together
● and explain why this friend is important to you.""",

    """Title: Describe a good habit you have
You should say:
● what the habit is
● how you developed it
● how it affects your life
● and explain why you think it is a good habit.""",

    """Title: Describe a long journey you had
You should say:
● where you went
● how you travelled
● what happened during the journey
● and explain how you felt about it.""",

    """Title: Describe a natural talent you have or have seen in someone else
You should say:
● what the talent is
● how you discovered it
● how it is used
● and explain how useful this talent is.""",

    """Title: Describe an old thing that has been in your family for a long time
You should say:
● what it is
● how long it has been in your family
● how your family first got it
● and explain why it is important.""",

    """Title: Describe a person you know who runs a family business
You should say:
● who the person is
● what the business is
● how successful it is
● and explain why you admire this person.""",

# ========================================================
    """Title: Describe a positive change you made in your daily routine
You should say:
● what the change was
● when you made it
● how it has affected your life
● and explain why you consider it a positive change.""",

    """Title: Describe a place with a lot of trees
You should say:
● where it is
● what it looks like
● what people do there
● and explain how you felt when you visited it.""",

    """Title: Describe something interesting you saw on social media
You should say:
● what it was
● when you saw it
● why you found it interesting
● and explain how it influenced you.""",

    """Title: Describe a time when you broke something
You should say:
● what it was
● how it happened
● how you felt about it
● and explain what you did afterwards.""",

    """Title: Describe the first time you spoke a foreign language
You should say:
● when it happened
● where you were
● who you spoke with
● and explain how you felt about it.""",

    """Title: Describe a successful sportsperson you admire
You should say:
● who the person is
● what sport he/she plays
● what achievements he/she has
● and explain why you admire this sportsperson.""",

    """Title: Describe a time when you told the truth
You should say:
● when it happened
● what the situation was
● what you said
● and explain how the other person reacted.""",

    """Title: Describe a toy you liked when you were a child
You should say:
● what it was
● who gave it to you
● how you played with it
● and explain why it was special to you.""",

    """Title: Describe a trip you would like to take again
You should say:
● where you went
● what you did there
● who you went with
● and explain why you would like to repeat this trip.""",

    """Title: Describe a water sport you want to try
You should say:
● what it is
● where you would do it
● how you would prepare for it
● and explain why you want to try it.""",

# ====================================================================

    """Title: Describe a wild animal you would like to know more about
You should say:
● what the animal is
● where it lives
● what you already know about it
● and explain why you want to know more about it.""",

    """Title: Describe a time you made a decision to wait for something
You should say:
● when it happened
● what you waited for
● why you made the decision
● and explain how you felt while waiting.""",

    """Title: Describe a famous person you would like to meet
You should say:
● who he/she is
● how you knew him/her
● where you would like to meet them
● and explain why you would like to meet them.""",


]




# ---------------------------------------------------------------------------
# Вставка в БД
# ---------------------------------------------------------------------------

async def seed() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        # Получаем уже существующие вопросы, чтобы не дублировать
        async with db.execute("SELECT text FROM topics") as cursor:
            existing = {row[0] for row in await cursor.fetchall()}

        new_questions = [q.strip() for q in QUESTIONS if q.strip() not in existing]

        if not new_questions:
            print("✅ All questions already exist in the database. Nothing to add.")
            return

        await db.executemany(
            "INSERT INTO topics (text) VALUES (?)",
            [(q,) for q in new_questions]
        )
        await db.commit()
        print(f"✅ Added {len(new_questions)} new question(s). "
              f"Skipped {len(QUESTIONS) - len(new_questions)} duplicate(s).")


if __name__ == "__main__":
    asyncio.run(seed())
