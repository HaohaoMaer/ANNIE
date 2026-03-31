# 🧠 AI NPC Narrative Simulation Engine
## 1. Project Overview
### 🎯 Goal
Build a **Multi-Agent Narrative Simulation Engine** that generates and drives **intelligent AI NPCs** with:
- Persistent memory
- Dynamic social relationships
- Autonomous decision-making
- Emergent storytelling
  This system is **not a chatbot**, but a **simulation engine** for:
- AI-driven storytelling
- Game NPC systems
- Complex character interaction modeling
## 2. Core Design Philosophy
### ❗ Key Principles
- Each NPC is an **independent Agent system**
- NPCs do **not own the world**, they perceive it
- Social relationships are **externalized**
- World progression is **event-driven + time-stepped**
- Context is **compressed and persisted**, not kept in prompt
## 3. High-Level Architecture
```text
AI NPC System Architecture
1. NPC Agent Layer
2. Social Graph Layer
3. World Engine Layer
```
## 4. NPC Agent Layer (LangGraph-based)
### 🧩 Overview
Each NPC is a **complete Agent system**, built using:
- LangGraph (workflow orchestration)
- LangChain (tools, memory, integrations)
### 🧠 Internal Structure
```text
NPC
 ├── Main Agent (LangGraph)
 │     ├── Planner        (task decomposition)
 │     ├── Executor       (action execution)
 │     └── Reflector      (memory update & reflection)
 │
 ├── Sub Agents
 │     ├── Memory Agent
 │     ├── Social Agent
 │     ├── Skill Agent
 │     └── Tool Agent
 │
 ├── Memory System
 │     ├── Episodic Memory      (events)
 │     ├── Semantic Memory      (knowledge)
 │     └── Relationship Memory  (subjective view)
 │
 ├── Skills (Modular)
 │     ├── Markdown definition
 │     ├── Script (Python)
 │     └── Prompt template
 │
 └── Tools
       ├── External APIs
       ├── File system
       └── Game interfaces
```
### ⚙️ Execution Flow
1. Receive input (event / interaction)
2. Planner decomposes task
3. Sub-agents invoked as needed:
   - Memory lookup
   - Social context
   - Skill selection
   - Tool usage
4. Execute actions
5. Reflect and update memory
## 5. Memory System Design
### 🧠 Types of Memory
#### 1. Episodic Memory
- Stores events
- Timestamped
- Example:
  - "Met NPC B at location X"
#### 2. Semantic Memory
- General knowledge
- Facts about world or self
#### 3. Relationship Memory
- Subjective perception of others
- Derived from Social Graph Layer
------
### 💾 Storage Strategy
- Long-term memory → persisted (DB / vector store / files)
- Context → compressed summaries
- Intermediate results → stored in file system
## 6. Skill System
### 🧩 Skill Format
Each skill consists of:
```text
Skill
 ├── Markdown (description)
 ├── Script (execution logic)
 └── Prompt Template
```
### ⚙️ Behavior
- Skills are **loaded on demand**
- Avoid context overload
- Reusable across NPCs
## 7. Social Graph Layer
### 🌐 Purpose
Decouple **relationship complexity** from NPC agents.
NPCs **query** this layer instead of managing relationships themselves.
### 🧩 Structure
```text
Social Graph
 ├── Nodes (NPCs)
 ├── Edges (Relationships)
 │     ├── Type (friend / enemy / lover / rival)
 │     ├── Intensity (0~1)
 │     └── Status (active / broken)
 │
 ├── Event Log (Event Sourcing)
 │     ├── Actor → Target → Action
 │     └── Timestamp
 │
 └── Propagation Engine
       ├── Gossip propagation
       ├── Trust filtering
       └── Time delay
```
### 🔑 Key Idea
- NPC sees **subjective world view**
- Global truth exists only in Social Graph
## 8. World Engine Layer
### 🎬 Role
Acts as a **“Director”** controlling:
- Time
- Events
- Environment
- Narrative pacing
### 🧩 Structure
```text
World Engine
 ├── Time System
 │     ├── Tick-based progression
 │     └── Day/Night cycles
 │
 ├── Event Scheduler
 │     ├── Timed events
 │     ├── Conditional triggers
 │     └── NPC action queue
 │
 ├── Scene Manager
 │     ├── Locations
 │     ├── Environment state
 │     └── NPC positions
 │
 └── Narrative Controller
       ├── Inject conflicts
       ├── Control pacing
       └── Trigger key events
```
## 9. NPC Initialization Design
### ❗ Important
NPC is **not initialized with a single prompt**
Instead, it is initialized with a **structured character definition**
### 🧩 Example
```yaml
npc:
  name: "Example NPC"
  personality:
    traits: ["calm", "rational"]
    values: ["logic", "efficiency"]
  background:
    biography: "..."
    past_events:
      - "..."
  goals:
    short_term: ["..."]
    long_term: ["..."]
  relationships:
    - target: "NPC_B"
      type: "friend"
      intensity: 0.7
  memory_seed:
    - "Initial important memory"
```
## 10. Model Configuration
### ⚙️ Config File
```yaml
model:
  provider: openai
  model_name: gpt-4
  temperature: 0.7
embedding:
  provider: openai
  model: text-embedding-3-large
```
## 11. Context Engineering Strategy
### 🧠 Techniques
- Context summarization
- Memory retrieval (RAG)
- Intermediate state persistence
- File-based storage for long tasks
## 12. Development Roadmap
### 🚀 Phase 1 (MVP)
- Single NPC
- Basic LangGraph agent
- Memory + Skill system
### 🚀 Phase 2
- Multiple NPCs
- Basic Social Graph
### 🚀 Phase 3
- World Engine (tick system)
- Event scheduling
### 🚀 Phase 4
- Emergent storytelling
- Narrative control
## 13. Final Vision
A system capable of:
- Simulating a living world
- Generating dynamic narratives
- Supporting AI-driven games
- Enabling long-term NPC evolution
## 🧩 One-line Summary
> A LangGraph-based multi-agent narrative simulation engine for generating intelligent NPCs with memory, relationships, and autonomous behavior.