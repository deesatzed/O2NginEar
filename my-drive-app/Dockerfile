# my-drive-app/Dockerfile
FROM node:18-alpine

WORKDIR /app

# Copy package.json and package-lock.json (or yarn.lock)
COPY package.json ./
# If using package-lock.json, uncomment next line
COPY package-lock.json ./
# If using yarn.lock, uncomment next line
# COPY yarn.lock ./

# Install dependencies
RUN npm install
# If using yarn, uncomment next line
# RUN yarn install

# Copy the rest of the application code
COPY . .

# React app's default port
EXPOSE 3000

# Command to start the React development server
# Using npm exec to ensure react-scripts is found, addressing potential PATH issues.
CMD ["npm", "exec", "react-scripts", "start"]
