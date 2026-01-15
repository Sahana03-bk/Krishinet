🌾 KrishiNet – Smart Agriculture Platform
📌 Project Summary

KrishiNet is a full-stack smart agriculture web application built using Python (Flask) that helps farmers sell crops, rent farming equipment, receive payments, and access real-time agriculture information such as market prices, government schemes, and news.

The project focuses on solving real farming problems by providing a single digital platform for farmers and buyers.

🎯 Why KrishiNet?

Farmers face problems such as:

Dependence on middlemen

Lack of fair pricing

No single platform for selling crops and renting equipment

Difficulty accessing government schemes and market prices

Manual payment processes

KrishiNet solves these problems using web technology and APIs.

🧩 Features Implemented
👨‍🌾 Farmer & User Features

User registration and login

Session-based authentication

Dashboard after login

Crop listing and marketplace

Equipment rental management

Profile management

💳 Payment System

Secure online payments using Stripe

Order tracking

Payment verification via webhook

📊 Information Services

Live agriculture news

Government scheme data

Crop market prices

🛠 Technology Stack
Backend (Core Logic)

Python

Flask

REST API architecture

Gunicorn (production server)

Frontend

HTML

CSS

Bootstrap

Jinja2 Templates

JavaScript (form handling, API calls)

Database

SQLite (users, orders, rentals, payments)

DevOps & Deployment

Docker

Render Cloud Platform

Environment Variables

Git & GitHub

🧠 Backend Architecture (Flask)

The backend follows REST API principles:

Method	Usage
GET	Fetch data (news, prices, products)
POST	Login, register, payments
PUT	Update profile, update orders
DELETE	Remove items

🔐 Environment Variables

Sensitive values are stored securely using environment variables:

DATA_GOV_API_KEY
SECRET_KEY
KRISHINET_DB
STRIPE_SECRET_KEY
STRIPE_PUBLISHABLE_KEY
STRIPE_WEBHOOK_SECRET
NEWSAPI_KEY


These are configured in Render dashboard, not pushed to GitHub.

Docker Workflow

Dockerfile defines Python 3.8 environment

Dependencies installed from requirements-prod.txt

Gunicorn starts Flask app

Render runs Docker container automatically

🚀 Deployment (Render + Docker)
Deployment Steps

Code pushed to GitHub

Render connects to repository

Docker builds application

Gunicorn runs Flask app

App is available publicly

Start Command
gunicorn app:app

Live URL

🔗 https://krishinet-8rx7.onrender.com

🔧 Tools & Packages Used

Flask

Gunicorn

Stripe

SQLite

Requests

Docker

Render

GitHub

👩‍💻 Developer Details

Name: Sahana B K
Course: MCA
Project: KrishiNet – Smart Agriculture Platform




