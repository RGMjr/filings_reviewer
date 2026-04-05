# L1 Diagrams Quick Reference

## 📋 Which Diagram Should I Use?

### For Developers
**→ Use: UML Component Diagram** (`L1_UML_COMPONENT_DIAGRAM.md`)

Shows all internal components and dependencies. Best for:
- Understanding the codebase structure
- Planning code changes or refactoring
- Tracing dependencies between modules
- Onboarding new team members
- Code reviews

### For Project Managers / Stakeholders
**→ Use: C4 System Context** (`L1_C4_SYSTEM_CONTEXT_DIAGRAM.md`)

Shows system boundaries and external integrations. Best for:
- Executive presentations
- Requirements gathering
- Risk assessment of external dependencies
- High-level project documentation
- Explaining what the system does

### For Architecture Discussions
**→ Use Both** with the comparison guide (`L1_DIAGRAM_COMPARISON.md`)

Provides complementary views:
- UML shows how things work internally
- C4 shows where the system fits in the world

### For Quick Understanding
**→ Use: Architecture Visualization** (`ARCHITECTURE_VISUALIZATION.md`)

Contains:
- Text-based ASCII diagrams
- Layer breakdown
- Data flow diagram
- Technology stack
- Architectural decisions

---

## 🎯 The Three-Diagram Set

| File | Purpose | Audience | Detail Level |
|------|---------|----------|--------------|
| **L1_UML_COMPONENT_DIAGRAM.md** | Internal architecture | Developers | High |
| **L1_C4_SYSTEM_CONTEXT_DIAGRAM.md** | System boundaries | Stakeholders | Low |
| **L1_DIAGRAM_COMPARISON.md** | Choose wisely | Everyone | Medium |

---

## 🚀 Quick Start

### If you have 2 minutes:
Read the "Quick Comparison Table" in `L1_DIAGRAM_COMPARISON.md`

### If you have 5 minutes:
1. View the ASCII diagrams in `ARCHITECTURE_VISUALIZATION.md`
2. Read "Component Layer Breakdown" section

### If you have 15 minutes:
1. Read the entire `ARCHITECTURE_VISUALIZATION.md`
2. Look at the "When to Use Each Model" section in `L1_DIAGRAM_COMPARISON.md`

### If you have 30 minutes:
1. Read all four documents in order:
   - `ARCHITECTURE_VISUALIZATION.md` (overview)
   - `L1_UML_COMPONENT_DIAGRAM.md` (details)
   - `L1_C4_SYSTEM_CONTEXT_DIAGRAM.md` (context)
   - `L1_DIAGRAM_COMPARISON.md` (how to choose)

---

## 🔍 Finding Information

### "How does data flow through the system?"
**→** `ARCHITECTURE_VISUALIZATION.md` → "Data Flow Diagram"

### "What are the main components?"
**→** `L1_UML_COMPONENT_DIAGRAM.md` → "Component Descriptions"

### "Who uses this system and why?"
**→** `L1_C4_SYSTEM_CONTEXT_DIAGRAM.md` → "Key Characteristics"

### "Which components depend on the database?"
**→** `L1_UML_COMPONENT_DIAGRAM.md` → Follow the arrows to "Database Adapter"

### "What external systems do we depend on?"
**→** `L1_C4_SYSTEM_CONTEXT_DIAGRAM.md` or `ARCHITECTURE_VISUALIZATION.md` → "External Dependencies"

### "How many stages are in the V2 extraction pipeline?"
**→** `L1_UML_COMPONENT_DIAGRAM.md` → Look at "Extraction V2" component (15 stages listed)

### "Can I redraw these diagrams?"
**→** `L1_DIAGRAM_COMPARISON.md` → "How to Render These Diagrams"

---

## 📚 Integration with Other Documentation

These diagrams complement:
- **CLAUDE.md** - Text-based architecture guide and implementation rules
- **docs/README.md** - Complete documentation index
- **.claude/rules/** - Detailed implementation guidelines

```
CLAUDE.md (principles & commands)
    ↓
DIAGRAM_QUICK_REFERENCE.md (you are here)
    ↓
UML Component Diagram (developer detail)
    ↓
Code in src/ (implementation)
```

---

## 🎨 Understanding the UML Diagram Colors

In the PlantUML code:
- **🟨 Yellow** = Components (main building blocks)
- **🔵 Blue** = External databases
- **🟩 Green** = External services
- **🟪 Purple** = LLM/Service layer

Styles by function:
- `<<infrastructure>>` - System-level services
- `<<business>>` - Core business logic
- `<<presentation>>` - User-facing interfaces
- `<<service>>` - Third-party integrations
- `<<testing>>` - Validation and testing
- `<<configuration>>` - Config and rules

---

## 🎨 Understanding the C4 Context Diagram

C4 model has 4 levels (we document L1):

**L1: System Context** (Filings Reviewer as a black box)
- What: Users + External Systems + Our System
- Who: Everyone
- When: Initial requirements, executive presentations

**L2: Containers** (Major runtime components - not yet documented)
- What: Flask, Database, Extraction Engine
- Who: Developers, architects
- When: Understanding deployment

**L3: Components** (Detailed subsystems - not yet documented)
- What: API Routes, V2 Stages, Review Manager
- Who: Developers implementing features
- When: Code reviews, detailed design

**L4: Code** (Classes, methods - see actual code in `src/`)
- What: Individual functions and classes
- Who: Developers writing code
- When: Implementation and debugging

---

## 💡 Key Insights from the Diagrams

### From UML Component Diagram:
1. **Hub-and-spoke**: Database Adapter is central hub
2. **Clear layers**: Infrastructure → Business → Presentation
3. **Dual extraction**: V1 and V2 coexist
4. **LLM is secondary**: Integration layer, not primary logic
5. **Configuration-driven**: metric_keywords.yaml is authoritative

### From C4 System Context:
1. **Three external systems**: SEC Edgar (data), OpenAI (analysis), HuggingFace (models)
2. **Two user types**: Analysts (users) and Auditors (validators)
3. **System boundary**: Clear separation between inside and outside
4. **Data direction**: Input from SEC Edgar, output to users
5. **External dependency risks**: OpenAI API availability, SEC Edgar uptime

---

## 🔗 File Locations

All diagrams are in the `docs/` directory:

```
docs/
├── L1_UML_COMPONENT_DIAGRAM.md          ← Developer view
├── L1_C4_SYSTEM_CONTEXT_DIAGRAM.md      ← Stakeholder view
├── L1_DIAGRAM_COMPARISON.md             ← How to choose
├── ARCHITECTURE_VISUALIZATION.md         ← Quick visual ref
├── DIAGRAM_QUICK_REFERENCE.md          ← This file
└── README.md                            ← Full documentation index
```

---

## ✅ Checklist: Using These Diagrams

- [ ] I know which diagram to use for my audience
- [ ] I understand the difference between UML and C4
- [ ] I can find specific components in the UML diagram
- [ ] I understand the system boundaries from C4
- [ ] I know the 7 architectural layers
- [ ] I can trace data flow through the system
- [ ] I understand which components depend on external APIs

---

## 🤔 Common Questions

**Q: Why are there two diagrams?**
A: UML shows internal complexity (for developers), C4 shows external context (for stakeholders). Different audiences need different views.

**Q: Which one is "correct"?**
A: Both are correct—they're just different perspectives. Like viewing a city from a map (C4) vs. a floor plan (UML).

**Q: Can I modify these diagrams?**
A: Yes! The PlantUML code is in the markdown files. Edit and re-render as needed when architecture changes.

**Q: Do I need both?**
A: No. Use whichever fits your current need:
- Coding? → UML
- Presenting? → C4
- Learning? → Both

**Q: Why are components organized by layer?**
A: Follows the principle of separation of concerns. Each layer has a specific responsibility.

---

## 📞 Questions or Feedback?

- **Architecture questions**: See CLAUDE.md
- **Implementation details**: See the actual code in `src/`
- **Diagram improvements**: Edit the PlantUML code in the markdown files
- **Documentation gaps**: Check docs/README.md for full index

