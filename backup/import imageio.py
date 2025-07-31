import imageio
import numpy as np
from PIL import Image

# Load the image
img = Image.open('IMG_3117.JPG')

# Make sure the size of the image is divisible by 16
width, height = img.size
width = width // 16 * 16
height = height // 16 * 16
img = img.resize((width, height))

# Convert the image to numpy array
img = np.array(img)

# Calculate the size of the cropped image
new_width = height * 3 // 2
step = 16
new_width = new_width // step * step

# Initialize the writer
writer = imageio.get_writer('panning_video.mp4', fps=30)

# Calculate the range of x for panning
x_range = list(range(0, width - new_width, step))  # From left to right

# Generate each frame and write to video
for x in x_range:
    frame = img[:, x:x+new_width]
    writer.append_data(frame)

# Close the writer
writer.close()
