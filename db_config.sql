-- Create the database
CREATE DATABASE IF NOT EXISTS examgen;
USE examgen;

-- Table 1: generated_questions
CREATE TABLE IF NOT EXISTS generated_questions (
  id INT NOT NULL AUTO_INCREMENT,
  question TEXT,
  options TEXT,
  answer TEXT,
  difficulty VARCHAR(50) DEFAULT NULL,
  type VARCHAR(50) DEFAULT NULL,
  created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Table 2: mcq_questions
CREATE TABLE IF NOT EXISTS mcq_questions (
  id INT NOT NULL AUTO_INCREMENT,
  user INT DEFAULT NULL,
  question TEXT,
  options TEXT,
  answer TEXT,
  PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Table 3: users
CREATE TABLE IF NOT EXISTS users (
  id INT NOT NULL AUTO_INCREMENT,
  username VARCHAR(100) DEFAULT NULL,
  email VARCHAR(100) DEFAULT NULL,
  password VARCHAR(200) DEFAULT NULL,
  PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Table 4: written_questions
CREATE TABLE IF NOT EXISTS written_questions (
  id INT NOT NULL AUTO_INCREMENT,
  user_id INT DEFAULT NULL,
  section_name VARCHAR(100) DEFAULT NULL,
  question TEXT,
  difficulty VARCHAR(20) DEFAULT NULL,
  marks INT DEFAULT NULL,
  created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY user_id (user_id),
  CONSTRAINT written_questions_ibfk_1 FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
