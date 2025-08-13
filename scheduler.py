from ortools.sat.python import cp_model

def solve_shift_schedule(employees, days, time_slots, unavailable, coverage, max_shifts):
    model = cp_model.CpModel()
    X = {}

    # Define variables
    for e in employees:
        for d in days:
            for t in time_slots:
                X[(e, d, t)] = model.NewBoolVar(f'X_{e}_{d}_{t}')

    # Unavailability
    for (e, d, t) in unavailable:
        model.Add(X[(e, d, t)] == 0)

    # Shift coverage
    for d in days:
        for t in time_slots:
            model.Add(sum(X[(e, d, t)] for e in employees) == coverage[(d, t)])

    # Max shifts per week
    for e in employees:
        model.Add(sum(X[(e, d, t)] for d in days for t in time_slots) <= max_shifts[e])

    # ❗ Add: One shift per day per employee
    for e in employees:
        for d in days:
            model.Add(sum(X[(e, d, t)] for t in time_slots) <= 1)

    # Solve
    solver = cp_model.CpSolver()
    status = solver.Solve(model)

    if status in [cp_model.FEASIBLE, cp_model.OPTIMAL]:
        result = [
            (e, d, t)
            for e in employees
            for d in days
            for t in time_slots
            if solver.Value(X[(e, d, t)]) == 1
        ]
        return result
    return None