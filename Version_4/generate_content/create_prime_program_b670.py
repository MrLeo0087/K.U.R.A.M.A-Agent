import os

# Define the directory and file paths
folder_path = r'D:\hello'
file_path = os.path.join(folder_path, 'main.py')

# Ensure the folder exists
os.makedirs(folder_path, exist_ok=True)

# Python program that checks if a number is prime
prime_program = '''
def is_prime(n: int) -> bool:
    """Return True if n is a prime number, else False."""
    if n <= 1:
        return False
    if n <= 3:
        return True
    if n % 2 == 0 or n % 3 == 0:
        return False
    i = 5
    while i * i <= n:
        if n % i == 0 or n % (i + 2) == 0:
            return False
        i += 6
    return True

if __name__ == "__main__":
    try:
        number = int(input("Enter an integer to test for primality: "))
    except ValueError:
        print("Invalid input. Please enter an integer.")
        exit(1)
    if is_prime(number):
        print(f"{number} is a prime number.")
    else:
        print(f"{number} is not a prime number.")
'''  # End of prime_program string

# Write the prime program to main.py
with open(file_path, 'w', encoding='utf-8') as f:
    f.write(prime_program)

print(f"Created {file_path} with prime number checker.")
