from parser import parse_node


def eval_expr(expr, env, sim=None):
    kind = expr[0]
    if kind == "num":
        return expr[1]
    if kind == "var":
        name = expr[1]
        if name not in env:
            raise RuntimeError(f"Unknown variable {name!r}")
        return env[name]
    if kind == "nodeattr":
        _, node_id, attr = expr
        if sim is None:
            raise RuntimeError("Cannot resolve @node.attr without simulator context")
        target = sim.registry.get(node_id)
        if target is None:
            raise RuntimeError(f"No node with id {node_id}")
        if attr == "dile":
            return target.dile
        if attr in target.vars:
            return target.vars[attr]
        raise RuntimeError(f"{target.name} has no state variable {attr!r}")
    if kind == "binop":
        _, op, l, r = expr
        lv, rv = eval_expr(l, env, sim), eval_expr(r, env, sim)
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
        # state vars only -- these are the only names write_env() will ever
        # commit back onto the node, so anything not listed here (e.g. a
        # function-local `var`) can never persist or leak to other nodes.
        self.vars = {var: eval_expr(expr, {}, sim) for var, expr in node_def.state.items()}

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
        # NOTE: no final self.write_env(env) here anymore -- see exec_block's
        # "assign" case for why. Every statement that can actually change
        # dile/vars now saves immediately when it happens, so there is
        # nothing left to save at the end -- and saving again here, from
        # this call's own possibly-outdated local copy, was exactly what
        # could silently undo a newer value written by someone else while
        # this call was still in progress deeper in the chain.

    def __repr__(self):
        return f"{self.name}({self.id}) dile={self.dile} {self.vars}"


def exec_block(stmts, env, self_node, sim):
    for stmt in stmts:
        kind = stmt[0]

        if kind == "assign":
            _, var, expr = stmt
            env[var] = eval_expr(expr, env, sim)
            # Save this change immediately, the moment it happens -- not
            # just once at the very end of the function. Waiting until the
            # end meant a function was working off an old copy of the
            # number the whole time; if another node changed the real
            # value in the meantime (by calling back in), the end-of-
            # function save would overwrite that newer value with the old
            # one. Saving right here means there's never an old copy left
            # sitting around to accidentally undo something newer.
            self_node.write_env(env)

        elif kind == "local_var":
            # function-closed variable: lives only in this call's env, never
            # written back onto self_node.vars (write_env only copies names
            # already declared in state:), so no other node -- and no later
            # call to this same function -- can ever see it.
            _, name, expr = stmt
            env[name] = eval_expr(expr, env, sim)

        elif kind == "if_chain":
            _, branches, else_body = stmt
            matched = False
            for cond, body in branches:
                if eval_expr(cond, env, sim):
                    exec_block(body, env, self_node, sim)
                    matched = True
                    break
            if not matched and else_body is not None:
                exec_block(else_body, env, self_node, sim)

        elif kind == "call":
            _, target_id, func_name, arg_exprs, label, tick_num = stmt

            if tick_num is not None and tick_num != "next" and sim.tick_count != tick_num:
                continue  # scheduled for a different absolute tick -- skip this one

            args = [eval_expr(a, env, sim) for a in arg_exprs]

            # Commit this node's progress BEFORE handing control to another
            # node's function. Previously this only happened once, after the
            # whole outer function returned -- so if A called B and B called
            # back into A before A's first call had returned, B would read
            # A's stale pre-call state (or vice versa in a mutual chain),
            # and a threshold IF-check comparing against that frozen value
            # could never see it cross, causing unbounded recursion. Writing
            # here means every call in a chain always sees the real,
            # up-to-date state of whoever it's calling.
            self_node.write_env(env)

            if tick_num == "next":
                # Don't run this call now -- queue it to fire at the START
                # of the NEXT tick, outside of this call stack entirely.
                # This is what actually stops a chain like A -> B -> A from
                # happening instantly, all within one tick: each hop now
                # waits for its own tick instead of running inside the call
                # that triggered it.
                sim.defer_call(self_node.id, target_id, func_name, args, label)
                continue

            ran = sim.handle_call(self_node.id, target_id, func_name, args, label)

            # Only resync from self_node's committed state when the call was
            # a genuine self-call AND it actually ran a function body. Labels
            # like "off" never run a function -- they just mutate
            # sim.behaviors -- so there's nothing new to pull back in, and
            # resyncing anyway would overwrite whatever this function just
            # computed locally with a stale value.
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
        self.deferred = {}  # tick_number -> list of (source_id, target_id, func_name, args, label)
        self.history = {node_id: [node.dile] for node_id, node in self.registry.items()}

        # Untagged top-level calls (no {tick:N}) fire ONCE, right here at
        # setup -- same as the very first version of this engine. Tagged
        # ones ({tick:N}) are NOT fired here; tick() below fires each of
        # those exactly once, when self.tick_count reaches that number.
        for node in list(self.registry.values()):
            for stmt in node.tick_calls:
                _, target_id, func_name, arg_exprs, label, tick_num = stmt
                if tick_num == "next":
                    # defer_call() uses tick_count+1; tick_count is still 0
                    # here (we're at setup, before tick 1), so this lands
                    # exactly on tick 1 -- the earliest a deferred call can
                    # ever fire.
                    args = [eval_expr(a, node.env(), self) for a in arg_exprs]
                    self.defer_call(node.id, target_id, func_name, args, label)
                    continue
                if tick_num is not None:
                    continue
                args = [eval_expr(a, node.env(), self) for a in arg_exprs]
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

    def defer_call(self, source_id, target_id, func_name, args, label):
        """Queue a call to fire at the start of the NEXT tick instead of
        running it right now. Args are captured now (frozen at the moment
        the call was made), not re-read when it actually fires later."""
        fire_at = self.tick_count + 1
        self.deferred.setdefault(fire_at, []).append((source_id, target_id, func_name, args, label))

    def run_deferred_calls(self):
        pending = self.deferred.pop(self.tick_count, [])
        for source_id, target_id, func_name, args, label in pending:
            self.handle_call(source_id, target_id, func_name, args, label)

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

    def run_tick_calls(self):
        """Fires any top-level call tagged {tick:N}, exactly when
        self.tick_count reaches N -- and only then, since tick_count hits
        each number exactly once per run. Untagged calls and {tick:next}
        calls are NOT handled here -- untagged fired once at setup, and
        {tick:next} calls go through the deferred-call queue instead."""
        for node in list(self.registry.values()):
            for stmt in node.tick_calls:
                _, target_id, func_name, arg_exprs, label, tick_num = stmt
                if tick_num is None or tick_num == "next" or tick_num != self.tick_count:
                    continue
                args = [eval_expr(a, node.env(), self) for a in arg_exprs]
                self.handle_call(node.id, target_id, func_name, args, label)

    def tick(self):
        self.log.append(f"[tick {self.tick_count}]")

        self.run_deferred_calls()
        self.run_tick_calls()

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
            # tick's number.
            self.tick_count = t
            if t in schedule:
                for node_id, func_name, args, label in schedule[t]:
                    self.inject(node_id, func_name, args, label)
            self.tick()
        return self.log