def calculator():
    print("Simple Calculator")
    while True:
        expr = input("Enter expression (e.g., 2 + 3) or 'quit' to exit: ")
        if expr.lower() in ('quit', 'exit'):
            break
        try:
            # Evaluate safely using eval with limited globals
            result = eval(expr, {"__builtins__": None}, {})
            print(f"Result: {result}")
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    calculator()
