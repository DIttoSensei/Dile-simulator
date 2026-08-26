from parser import parse_node


def eval_expr(expr, env):
    kind = expr[0]
    if kind == "num":
        return expr[1]
    if kind == "var":
        name = expr[1]
        if name not in env:
            raise RuntimeError(f"Unknown variable {name!r}")
        return env[name]
    if kind == "binop":
        _, op, l, r = expr
        lv, rv = eval_expr(l, env), eval_expr(r, env)
        ops = {
            "+": lambda a, b: a + b, "-": lambda a, b: a - b,
            "*": lambda a, b: a * b, "/": lambda a, b: a / b,
            "<": lambda a, b: a < b, ">": lambda a, b: a > b,
            "<=": lambda a, b: a <= b, ">=": lambda a, b: a >= b,
            "==": lambda a, b: a == b, "!=": lambda a, b: a != b,
        }
        return ops[op](lv, rv)
    raise RuntimeError(f"Cannot evaluate {expr!r}")


class NodeInstance:
    def __init__(self, node_def, sim):
        self.id = node_def.id
        self.name = node_def.name
        self.base_dile = node_def.base_dile
        self.functions = node_def.functions
        self.has_decay = node_def.has_decay
        self.tick_calls = getattr(node_def, "tick_calls", [])
        self.sim = sim
        self.dile = node_def.base_dile
        self.vars = {var: eval_expr(expr, {}) for var, expr in node_def.state.items()}

    def env(self):
        e = dict(self.vars)
        e["dile"] = self.dile
        return e

    def write_env(self, env):
        self.dile = env["dile"]
        for var in self.vars:
            if var in env:
                self.vars[var] = env[var]

    def run_function(self, func_name, args):
        fn = self.functions.get(func_name)
        if fn is None:
            raise RuntimeError(f"{self.name} has no function {func_name!r}")
        env = self.env()
        for param, val in zip(fn.params, args):
            env[param] = val
        exec_block(fn.body, env, self, self.sim)
        self.write_env(env)

    def __repr__(self):
        return f"{self.name}({self.id}) dile={self.dile} {self.vars}"


def exec_block(stmts, env, self_node, sim):
    for stmt in stmts:
        kind = stmt[0]
        if kind == "assign":
            _, var, expr = stmt
            env[var] = eval_expr(expr, env)
        elif kind == "if":
            _, cond, body = stmt
            if eval_expr(cond, env):
                exec_block(body, env, self_node, sim)
        elif kind == "call":
            _, target_id, func_name, arg_exprs, label = stmt
            args = [eval_expr(a, env) for a in arg_exprs]
            ran = sim.handle_call(self_node.id, target_id, func_name, args, label)
            # Only resync from self_node's committed state when the call was
            # a genuine self-call (target_id == self_node.id) AND that call
            # actually executed a function body (ran == True). Labels like
            # "off" never run a function -- they just mutate sim.behaviors --
            # so there is nothing new to pull back in. Resyncing anyway would
            # overwrite whatever this function just computed locally (e.g.
            # `dile = dile - amount`) with the stale pre-call value, since
            # self_node hasn't been write_env'd yet mid-function.
            if target_id == self_node.id and ran:
                env["dile"] = self_node.dile
                for v in self_node.vars:
                    env[v] = self_node.vars[v]
        else:
            raise RuntimeError(f"Unknown statement {kind!r}")


class Simulator:
    def __init__(self, node_defs):
        self.registry = {}
        for node_id, nd in node_defs.items():
            self.registry[node_id] = NodeInstance(nd, self)
        self.behaviors = {}
        self.log = []
        self.events = []
        self.tick_count = 0
        self.history = {node_id: [node.dile] for node_id, node in self.registry.items()}

        for node in self.registry.values():
            for stmt in node.tick_calls:
                _, target_id, func_name, arg_exprs, label = stmt
                args = [eval_expr(a, node.env()) for a in arg_exprs]
                self.handle_call(node.id, target_id, func_name, args, label)

    def handle_call(self, source_id, target_id, func_name, args, label):
        """Runs (or registers) a call. Returns True iff a function body was
        actually executed on the target node (i.e. dile/vars may have
        changed), False otherwise (e.g. label == "off", or a push that was
        already registered)."""
        target = self.registry.get(target_id)
        if target is None:
            raise RuntimeError(f"No node with id {target_id}")

        key = (source_id, target_id, func_name)
        external = source_id == "EXTERNAL"
        ran = False

        if label == "once":
            before = target.dile
            target.run_function(func_name, args)
            ran = True
            after = target.dile
            self.log.append(f"  {source_id} -> {target.name}.{func_name}({args}) [once]")
            self.events.append({
                "tick": self.tick_count, "source_id": source_id, "target_id": target_id,
                "func_name": func_name, "args": args, "label": "once", "external": external,
                "effect": f"dile {before} -> {after}",
            })

        elif label == "active":
            before = target.dile
            target.run_function(func_name, args)
            ran = True
            after = target.dile
            self.log.append(f"  {source_id} -> {target.name}.{func_name}({args}) [active: fires once, holds]")
            self.behaviors[key] = {"label": "active", "args": args}
            self.events.append({
                "tick": self.tick_count, "source_id": source_id, "target_id": target_id,
                "func_name": func_name, "args": args, "label": "active", "external": external,
                "effect": f"dile {before} -> {after} (now holding)",
            })

        elif label == "push":
            already = key in self.behaviors
            self.behaviors[key] = {"label": "push", "args": args}
            if not already:
                before = target.dile
                target.run_function(func_name, args)
                ran = True
                after = target.dile
                self.log.append(f"  {source_id} -> {target.name}.{func_name}({args}) [push: registered]")
                self.events.append({
                    "tick": self.tick_count, "source_id": source_id, "target_id": target_id,
                    "func_name": func_name, "args": args, "label": "push", "external": external,
                    "effect": f"dile {before} -> {after} (registered)",
                })

        elif label == "off":
            matches = [k for k in self.behaviors if k[1] == target_id and k[2] == func_name]
            for k in matches:
                del self.behaviors[k]
                self.log.append(f"  {source_id} -> {target.name}.{func_name} [off: cancelled]")
                self.events.append({
                    "tick": self.tick_count, "source_id": k[0], "target_id": target_id,
                    "func_name": func_name, "args": [], "label": "off", "external": k[0] == "EXTERNAL",
                    "effect": "cancelled",
                })

        else:
            raise RuntimeError(f"Unknown label {label!r}")

        return ran

    def inject(self, node_id, func_name, args, label="once"):
        self.handle_call("EXTERNAL", node_id, func_name, args, label)

    def compute_priority_bonus(self, contested_targets):
        wins = {}
        for target_id, entries in contested_targets.items():
            if len(entries) < 2:
                continue
            best_source = max(entries, key=lambda e: self.registry[e[0]].base_dile)[0]
            wins[best_source] = wins.get(best_source, 0) + 1
        ranked = sorted(wins.items(), key=lambda kv: -kv[1])
        bonus = {}
        for i, (source_id, _) in enumerate(ranked):
            bonus[source_id] = max(26 - i, 0)
        return bonus

    def resolve_contentions(self):
        contested_targets = {}
        for key in self.behaviors:
            source_id, target_id, func_name = key
            contested_targets.setdefault(target_id, []).append((source_id, key))

        bonus = self.compute_priority_bonus(contested_targets)

        winners = set()
        for target_id, entries in contested_targets.items():
            if len(entries) == 1:
                winners.add(entries[0][1])
                continue

            def strength(entry):
                source_id, _ = entry
                return self.registry[source_id].base_dile + bonus.get(source_id, 0)

            best = max(entries, key=strength)
            winners.add(best[1])
        return winners

    def held_targets(self):
        return {target_id for (_, target_id, _) in self.behaviors}

    def tick(self):
        self.log.append(f"[tick {self.tick_count}]")

        winners = self.resolve_contentions()
        held = self.held_targets()

        for key, info in list(self.behaviors.items()):
            if info["label"] != "push":
                continue
            if key not in winners:
                continue
            source_id, target_id, func_name = key
            target = self.registry[target_id]
            before = target.dile
            target.run_function(func_name, info["args"])
            after = target.dile
            self.log.append(f"  {source_id} -> {target.name}.{func_name}({info['args']}) [push: re-fired]")
            self.events.append({
                "tick": self.tick_count, "source_id": source_id, "target_id": target_id,
                "func_name": func_name, "args": info["args"], "label": "push",
                "external": source_id == "EXTERNAL",
                "effect": f"dile {before} -> {after} (re-fired)",
            })

        for node_id, node in self.registry.items():
            if node.has_decay and node_id not in held:
                if node.dile > node.base_dile:
                    node.dile -= 1
                elif node.dile < node.base_dile:
                    node.dile += 1

        for node_id, node in self.registry.items():
            self.history[node_id].append(node.dile)

    def run(self, ticks, schedule=None):
        schedule = schedule or {}
        for t in range(1, ticks + 1):
            # Set tick_count for this iteration BEFORE any scheduled
            # injections fire, so events logged by inject() carry the tick
            # they were actually scheduled for instead of the previous
            # tick's number (tick_count used to only advance inside
            # tick(), which runs after injections in the same iteration).
            self.tick_count = t
            if t in schedule:
                for node_id, func_name, args, label in schedule[t]:
                    self.inject(node_id, func_name, args, label)
            self.tick()
        return self.log