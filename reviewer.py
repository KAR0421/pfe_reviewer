import re
from collections import defaultdict

# simple generic variable patterns we consider bad
GENERIC_VARS = [r'\btmp\d*\b', r'\bvar[A-Z]?\b', r'\btemp\b']

# regex to match if/while/do conditions
CONDITION_REGEX = re.compile(r'\b(if|while|do)\s*\((.*?)\)', re.IGNORECASE)

# comparison operators: longest first to avoid conflicts
OPERATORS = ['!=', '>=', '<=', '>', '<', '=']

# -----------------------------
# EXISTING CHECKS
# -----------------------------
def check_naming_conventions(script):
    issues = []
    for pattern in GENERIC_VARS:
        matches = re.findall(pattern, script)
        if matches:
            issues.append(f"Generic variable names found: {', '.join(set(matches))}")
    return issues

def check_minimal_documentation(bizrule):
    issues = []
    if not bizrule.comment or bizrule.comment.strip() == "":
        issues.append("Missing or empty USER_COMMENT")
    return issues

def check_logs(script):
    """Analyze logs: verbose in loops or too few logs in complex code"""
    issues = []

    lines = [l.rstrip() for l in script.splitlines()]
    
    loop_pattern = re.compile(r'\b(for|foreach|while|do)\b')
    log_pattern = re.compile(r'\bmsg(info|error|warn)\(')

    inside_loop = False
    for i, line in enumerate(lines, 1):
        if loop_pattern.search(line):
            inside_loop = True
        if inside_loop and log_pattern.search(line):
            issues.append(f"Verbose log detected inside loop at line {i}: {line.strip()}")
            inside_loop = False  # warn once per loop

    # Complex script with too few logs
    num_logs = sum(bool(log_pattern.search(l)) for l in lines)
    if len(lines) > 50 and num_logs < 3:
        issues.append(f"Complex script ({len(lines)} lines) has too few logs ({num_logs})")

    return issues

def check_static_conditions(script):
    """Check for conditions that are always true/false or use only literals."""
    issues = []
    lines = [l.rstrip() for l in script.splitlines()]

    for i, line in enumerate(lines, 1):
        match = CONDITION_REGEX.search(line)
        if not match:
            continue

        condition = match.group(2).strip()
        found_operator = False

        for op in OPERATORS:
            if op in condition:
                found_operator = True
                left, right = condition.split(op, 1)
                left = left.strip()
                right = right.strip()

                # check if both sides are literals (numbers or strings)
                left_literal = re.match(r'^-?\d+(\.\d+)?$|^".*"$|^\'.*\'$', left)
                right_literal = re.match(r'^-?\d+(\.\d+)?$|^".*"$|^\'.*\'$', right)

                if left_literal and right_literal:
                    issues.append(f"Always true/false condition at line {i}: {line.strip()}")
                elif left == right:
                    issues.append(f"Redundant comparison at line {i}: {line.strip()}")
                break

        if not found_operator:
            single_literal = re.match(r'^-?\d+(\.\d+)?$|^".*"$|^\'.*\'$', condition)
            if single_literal:
                issues.append(f"Condition with only literal at line {i}: {line.strip()}")

    return issues

def check_dead_code(script):
    issues = []
    lines = script.splitlines()
    TERMINATORS = ["return", "abort", "skip"]

    for i, line in enumerate(lines):
        stripped = line.strip()
        found_term = None
        for term in TERMINATORS:
            if re.search(rf"\b{term}\b", stripped):
                found_term = term
                break

        if not found_term:
            continue

        if stripped.startswith(("if", "while", "for", "foreach")):
            continue

        j = i + 1
        while j < len(lines) and lines[j].strip() == "":
            j += 1

        if j < len(lines):
            next_line = lines[j].strip()
            if next_line != "}":
                issues.append(
                    f"Dead code after terminator '{found_term}' at line {i+1}: {next_line}"
                )

    return issues

def check_sql_in_loops(script):
    """Detect SQL queries executed inside loops (performance issue)."""
    issues = []

    lines = script.splitlines()
    loop_pattern = re.compile(r'\b(for|foreach|while|do)\b', re.IGNORECASE)
    sql_pattern = re.compile(r'\b(SELECT|INSERT|UPDATE|DELETE)\b', re.IGNORECASE)

    inside_loop = False
    loop_start_line = 0

    for i, line in enumerate(lines, 1):
        stripped = line.strip()

        if loop_pattern.search(stripped):
            inside_loop = True
            loop_start_line = i
            continue

        if inside_loop and sql_pattern.search(stripped):
            issues.append(
                f"SQL query inside loop starting at line {loop_start_line}: line {i} -> {stripped}"
            )
            inside_loop = False  # warn once per loop

        if inside_loop and stripped == "}":
            inside_loop = False

    return issues

def check_nested_loops(script):
    """Detect nested loops (potential performance issue)."""
    issues = []
    lines = script.splitlines()
    loop_pattern = re.compile(r'\b(for|foreach|while|do)\b', re.IGNORECASE)
    loop_stack = []

    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if loop_pattern.search(stripped):
            loop_stack.append(i)
            if len(loop_stack) > 1:
                issues.append(
                    f"Nested loop detected: outer loop at line {loop_stack[-2]}, inner loop at line {i}"
                )
        if stripped == "}" and loop_stack:
            loop_stack.pop()

    return issues

# -----------------------------
# NEW: repeated query detection
# -----------------------------
def check_repeated_queries(script):
    """Detect duplicate or similar SQL queries and track variable changes."""
    issues = []
    lines = script.splitlines()
    variable_updates = defaultdict(list)

    # Track variable assignments
    for i, line in enumerate(lines, 1):
        match = re.match(r'(\w+)\s*:=', line.strip())
        if match:
            variable_updates[match.group(1)].append(i)

    # Extract queries
    query_pattern = re.compile(r'(\w+)\s*:=\s*"(select .*?)"\s*.*?\n.*?getSqlData\(\1\)', re.IGNORECASE | re.DOTALL)
    queries = []
    for m in query_pattern.finditer(script):
        var_name = m.group(1)
        query = m.group(2)
        start_line = script[:m.start()].count("\n") + 1
        queries.append({"var": var_name, "query": query, "line": start_line})

    # Compare queries
    for i in range(len(queries)):
        for j in range(i + 1, len(queries)):
            q1 = queries[i]
            q2 = queries[j]

            norm1 = re.sub(r'\+\s*\w+', '+VAR', q1["query"]).lower()
            norm2 = re.sub(r'\+\s*\w+', '+VAR', q2["query"]).lower()

            vars1 = set(re.findall(r'\b[a-zA-Z_]\w*\b', q1["query"]))
            vars2 = set(re.findall(r'\b[a-zA-Z_]\w*\b', q2["query"]))

            # EXACT same query
            if norm1 == norm2:
                common_vars = vars1.intersection(vars2)
                updated = any(
                    any(l for l in variable_updates[v] if q1["line"] < l < q2["line"])
                    for v in common_vars
                )
                if not updated:
                    issues.append(f"DUPLICATE query at lines {q1['line']} and {q2['line']}")
            # Same structure, different variables
            elif norm1.split("where")[0] == norm2.split("where")[0]:
                issues.append(f"SIMILAR query structure at lines {q1['line']} and {q2['line']} (consider refactoring)")

    return issues

# -----------------------------
# MAIN REVIEW FUNCTION
# -----------------------------
def review_bizrule(bizrule):
    report = {"name": bizrule.name, "issues": []}

    report["issues"].extend(check_naming_conventions(bizrule.script))
    report["issues"].extend(check_minimal_documentation(bizrule))
    report["issues"].extend(check_logs(bizrule.script))
    report["issues"].extend(check_static_conditions(bizrule.script))
    report["issues"].extend(check_dead_code(bizrule.script))

    # NEW PERFORMANCE / STRUCTURE CHECKS
    report["issues"].extend(check_sql_in_loops(bizrule.script))
    report["issues"].extend(check_nested_loops(bizrule.script))
    report["issues"].extend(check_repeated_queries(bizrule.script))

    return report