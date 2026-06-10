# ⚡ PyCache

PyCache is a high-performance distributed in-memory key-value store inspired by Redis and built using Python. It provides fast data storage and retrieval, TTL (Time-To-Live) support, persistence through Append-Only Files (AOF), real-time monitoring, and an interactive dashboard powered by Streamlit.

---

## 🚀 Features

- Fast in-memory key-value storage
- Redis-inspired command execution
- TTL (Time-To-Live) support for automatic key expiration
- Append-Only File (AOF) persistence
- Real-time monitoring dashboard
- Cache hit and miss tracking
- Memory usage statistics
- Active connection monitoring
- Interactive command terminal
- Database management operations

---

## 🏗️ System Architecture

```text
User
  │
  ▼
PyCache Dashboard (Streamlit)
          │
          ▼
TCP Socket Server (server.py)
          │
          ▼
Storage Engine (engine.py)
          │
          ▼
AOF Persistence Layer (aof.py)
```

---

## 📸 Dashboard Overview

The PyCache dashboard provides a real-time view of the system's health and performance. It displays total keys, memory usage, cache hit rate, active connections, cache hits, and cache misses through an intuitive user interface.

[Dashboard Overview]:
<img width="1884" height="864" alt="Screenshot 2026-06-08 130747" src="https://github.com/user-attachments/assets/16558068-403c-4ec4-b54f-862a21d89bf9" />


---

## 💾 Database Operations

The integrated command terminal allows users to execute Redis-inspired commands such as SET, GET, KEYS, DBSIZE, and INFO. This makes it easy to interact with the database and monitor its behavior in real time.

![Database Operations](screenshots/database-operations.png)

---

## ⏳ TTL (Time-To-Live) Support

PyCache supports automatic key expiration using TTL. Users can assign expiration times to keys, and the system automatically removes them once the specified duration has elapsed.

Example:

```text
SET temp hello EX 30
```

![TTL Demonstration](screenshots/ttl-demo.png)

---

## 🗑️ Database Reset (FLUSHALL)

The FLUSHALL command instantly removes all stored keys from the database while keeping the server online and operational. This is useful for testing and resetting the system.

![FLUSHALL Demo](screenshots/flushall-demo.png)

---

## 📂 Project Structure

```text
PyCache/
│
├── app.py
├── server.py
├── engine.py
├── aof.py
├── traffic_simulator.py
├── requirements.txt
│
├── screenshots/
│   ├── dashboard-overview.png
│   ├── database-operations.png
│   ├── ttl-demo.png
│   └── flushall-demo.png
│
└── README.md
```

---

## 🛠️ Supported Commands

| Command | Description |
|----------|-------------|
| SET key value | Store a key-value pair |
| GET key | Retrieve the value of a key |
| DEL key | Delete one or more keys |
| EXISTS key | Check whether a key exists |
| TTL key | View remaining expiration time |
| KEYS | List all stored keys |
| DBSIZE | Show total number of keys |
| INFO | Display server statistics |
| PING | Check server status |
| FLUSHALL | Remove all keys |

---

## ⚙️ Installation

Clone the repository:

```bash
git clone https://github.com/YOUR_USERNAME/pycache.git
cd pycache
```

Create a virtual environment:

```bash
python -m venv .venv
```

Activate the environment:

Windows:

```bash
.venv\Scripts\activate
```

Linux / Mac:

```bash
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

---

## ▶️ Running the Project

Start the backend server:

```bash
python server.py
```

Open a new terminal and start the dashboard:

```bash
streamlit run app.py
```

Access the dashboard:

```text
http://localhost:8501
```

---

## 📊 Metrics Tracked

- Total Keys
- Memory Usage
- Active Connections
- Cache Hits
- Cache Misses
- Cache Hit Rate
- Expired Keys
- Database Size

---

## 🧪 Tech Stack

- Python
- Streamlit
- Socket Programming
- Multithreading
- AOF Persistence
- In-Memory Data Structures

---

## 🎯 Learning Outcomes

This project demonstrates practical knowledge of:

- Database Internals
- Client-Server Architecture
- Socket Programming
- Caching Systems
- Persistence Mechanisms
- System Design Concepts
- Dashboard Development

---

## 🔮 Future Enhancements

- Authentication and Role-Based Access Control
- Replication Support
- Distributed Clustering
- REST API Integration
- Advanced Monitoring and Analytics
- Docker Deployment
- Cloud Hosting Support

---

## 👩‍💻 Author

**Triveni Maddiboina**

B.Tech Computer Science Engineering Student  
Python Developer | Software Engineering Enthusiast

---

⭐ If you found this project useful, consider giving it a star.
