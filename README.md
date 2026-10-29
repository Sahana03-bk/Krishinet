# 🌾 KrishiNet – Smart Agriculture Platform

## 📌 Project Overview

KrishiNet is a full-stack smart agriculture web application built using **Python and Flask**. It helps farmers sell crops, rent agricultural equipment, receive online payments, and access agricultural information such as market prices, government schemes, and news.

The platform aims to connect farmers and buyers through a single digital solution.

## 🎯 Problem Statement

Farmers often face challenges such as:

- Dependence on intermediaries.
- Difficulty finding fair crop prices.
- Limited access to agricultural equipment rental services.
- Difficulty accessing government schemes and market information.
- Manual payment and transaction processes.

**KrishiNet aims to address these challenges through web technologies and API integration.**

## ✨ Key Features

### 👨‍🌾 Farmer and User Management

- User registration and login.
- Session-based authentication.
- Personalized dashboards.
- Profile management.
- Crop listing and marketplace.
- Agricultural equipment rental management.

### 💳 Payment Integration

- Stripe payment integration.
- Order and transaction management.
- Payment verification through webhooks.

### 📊 Agricultural Information

- Agricultural news.
- Crop market price information.
- Government schemes and loan information.

## 🛠️ Technology Stack

| Component | Technologies |
|---|---|
| Backend | Python, Flask |
| Frontend | HTML, CSS, Bootstrap, JavaScript |
| Templating | Jinja2 |
| Database | SQLite |
| API Integration | REST APIs, Requests |
| Payment Gateway | Stripe |
| Production Server | Gunicorn |
| Containerization | Docker |
| Cloud Deployment | Render |
| Version Control | Git, GitHub |

## 🧠 Backend Architecture

The application uses Flask to handle application logic, requests, authentication, database operations, and API integrations.

### HTTP Methods

| Method | Purpose |
|---|---|
| GET | Retrieve information |
| POST | Submit data, register, log in, or initiate actions |
| PUT | Update existing resources |
| DELETE | Remove resources |

*These methods describe the API design where implemented.*

## 🔐 Environment Configuration

Sensitive configuration values are managed through environment variables rather than being committed to the GitHub repository.

Examples include:

- `SECRET_KEY`
- `KRISHINET_DB`
- `DATA_GOV_API_KEY`
- `NEWSAPI_KEY`
- `STRIPE_SECRET_KEY`
- `STRIPE_PUBLISHABLE_KEY`
- `STRIPE_WEBHOOK_SECRET`

Configure the required variables in the Render dashboard. Never publish secret keys or passwords in your repository.

## 🐳 Docker and Deployment

KrishiNet is containerized using Docker and deployed on Render Cloud.

### Deployment Workflow

1. Push source code to GitHub.
2. Connect the GitHub repository to Render.
3. Build the application using the Dockerfile.
4. Install dependencies from `requirements-prod.txt`.
5. Start the Flask application using Gunicorn.
6. Access the deployed application through its public URL.

### Production Start Command

```bash
gunicorn app:app
```

## 🚀 Live Application

**Live Demo:** https://krishinet-8rx7.onrender.com

You can register a new account on the application to explore its available features.

## 🔑 Demo Access

If a dedicated demo account is configured, provide its credentials here.

- **Email:** `sahanakgowda2003@gmail.com`
- **Password:** `Sahana@2003`

*Replace these placeholders with working demo credentials before sharing. Do not use personal account credentials.*

## ⚙️ Installation and Setup

### Prerequisites

- Python
- Git
- Docker (optional for local containerized setup)

### Run Locally

```bash
# Clone the repository
git clone https://github.com/Sahana03-bk/Krishinet.git

# Navigate to the project directory
cd Krishinet

# Create a virtual environment
python -m venv venv

# Activate on Windows
venv\Scripts\activate

# Install dependencies
pip install -r requirements-prod.txt

# Start the application
python app.py
```

*Configure the required environment variables before running the application. Use the actual dependency file and startup instructions in your repository.*

## 👩‍💻 Developer

**Name:** Sahana B K

**Qualification:** Master of Computer Applications (MCA)

**Project:** KrishiNet – Smart Agriculture Platform

**GitHub:** https://github.com/Sahana03-bk

**Live Application:** https://krishinet-8rx7.onrender.com
