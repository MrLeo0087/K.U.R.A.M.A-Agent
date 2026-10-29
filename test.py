import pandas as pd
import numpy as np

# Define column names
columns = ['a', 'b', 'c', 'd']

# Generate random data: 10 rows, 4 columns
data = np.random.randn(10, 4)

# Create DataFrame
df = pd.DataFrame(data, columns=columns)

# Display the DataFrame
print(df)
