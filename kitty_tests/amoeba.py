#!/usr/bin/env python
# License: GPL v3 Copyright: 2026, kitty contributors

from kitty.fast_data_types import AmoebaError, AmoebaSolver

from .base import BaseTest


class TestAmoeba(BaseTest):
    def test_python_bindings(self) -> None:
        solver = AmoebaSolver()
        x, y = solver.add_variable(), solver.add_variable()
        solver.add_constraint(((x, 1.0), (y, 1.0)), '==', 10.0)
        solver.add_constraint(((x, 1.0), (y, -1.0)), '==', 4.0)
        solver.update_variables()
        self.ae(solver.value(x), 7)
        self.ae(solver.value(y), 3)

        edited = AmoebaSolver()
        total, first, second = (edited.add_variable() for _ in range(3))
        edited.add_edit_variable(total, 1_000_000)
        edited.add_constraint(((first, 1.0), (second, 1.0), (total, -1.0)), '==', 0.0)
        edited.add_constraint(((first, 1.0), (total, -0.25)), '==', 0.0)
        edited.suggest_value(total, 100)
        edited.update_variables()
        self.ae((edited.value(first), edited.value(second)), (25, 75))
        edited.suggest_value(total, 80)
        edited.update_variables()
        self.ae((edited.value(first), edited.value(second)), (20, 60))

        with self.assertRaises(AmoebaError):
            solver.add_constraint(((x, 1.0),), '==', 100.0)
