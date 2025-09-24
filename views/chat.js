
import { GoogleGenerativeAI, HarmCategory, HarmBlockThreshold } from "@google/generative-ai";

import { Slide_text_data } from "../packages/slide_text_data.mjs"
console.log(Slide_text_data);

const sendBtn = document.getElementById("send-btn");
const chatBotInput = document.getElementById("chatbot-input");
const chatbotMessages = document.getElementById("chatbot-messages");


const API_KEY = "AIzaSyAdDJjgNJY5gpRSHLUpONtOEYs9_tmt-Nk"; 

let genAI;
let chat; 
function appendSystemMessage(message, isError = false) {
    if (!chatbotMessages) return;
    const messageElement = document.createElement("div");
    messageElement.className = `message system ${isError ? 'error' : ''}`; // Add 'error' class for specific styling
    messageElement.textContent = message;
    chatbotMessages.appendChild(messageElement);
    chatbotMessages.scrollTop = chatbotMessages.scrollHeight;
}


if (API_KEY === "YOUR_API_KEY") {
     // Use the new system message function
     appendSystemMessage("Please replace 'YOUR_API_KEY' in the script tag with your actual Google AI API key.", true); // Mark as error
}


try {
    genAI = new GoogleGenerativeAI(API_KEY);
    const model = genAI.getGenerativeModel({
         model: "gemini-1.5-flash",
         safetySettings: [ // Keep safety settings
            { category: HarmCategory.HARM_CATEGORY_HARASSMENT, threshold: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE },
            { category: HarmCategory.HARM_CATEGORY_HATE_SPEECH, threshold: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE },
            { category: HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, threshold: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE },
            { category: HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, threshold: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE },
        ]
     });

    chat = await model.startChat({ history: [ ] }); 
    const initialpromt=`Act as an AI assistant that only answers questions strictly based on presentation slide data or related to that that . If the user asks something irrelevant, reply: "Please ask relevant questions only." Do not break this rule under any circumstances. ${Slide_text_data}`

    try {
    const result = await chat.sendMessage(initialpromt);
    console.log(" System prompt sent successfully.");
} catch (error) {



    
    console.error(" Failed to send initial system prompt:", error);
    appendSystemMessage("Failed to send the initial instruction to AI.", true);
}

} catch (error) {
    console.error("Error initializing GoogleGenerativeAI SDK:", error);
    appendSystemMessage(`Error initializing AI: ${error.message}. Check console and API Key.`, true); // Mark as error
    if (chatBotInput) chatBotInput.disabled = true;
    if (sendBtn) sendBtn.disabled = true;
}


// --- Event Listeners ---
if (sendBtn) {
    sendBtn.addEventListener("click", sendMessage);
}

if (chatBotInput) {
    chatBotInput.addEventListener("keypress", (e) => {
        if (e.key === "Enter") {
            e.preventDefault();
            sendMessage();
        }
    });
}

// --- Chat Functions ---
function sendMessage() {
    // Check if chat is initialized properly before sending
     if (!chat) {
        console.error("Chat session not initialized. Cannot send message.");
        appendSystemMessage("Cannot send message. AI Initialization may have failed.", true); // Mark as error
        return;
    }
    const userMessage = chatBotInput.value.trim();
    if (userMessage) {
        appendMessage("user", userMessage); 
        chatBotInput.value = "";
        chatBotInput.disabled = true;
        sendBtn.disabled = true;
        getBotResponse(userMessage); 
    }
}

function appendMessage(sender, message) {
    if (!chatbotMessages) return;
    const messageElement = document.createElement("div");
    
    messageElement.className = `message ${sender}`;


    let formattedMessage = message.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    formattedMessage = formattedMessage.replace(/\*(.*?)\*/g, '<em>$1</em>');

    messageElement.innerHTML = formattedMessage; 
    chatbotMessages.appendChild(messageElement);
    chatbotMessages.scrollTop = chatbotMessages.scrollHeight;
}


async function getBotResponse(userMessage) {
     if (!chat) { 
         console.error("Chat session not initialized.");
         appendSystemMessage("Sorry, the chat session is not available.", true); 
         if (chatBotInput) chatBotInput.disabled = false;
         if (sendBtn) sendBtn.disabled = false;
         return;
     }


    const typingIndicator = document.createElement("div");
    typingIndicator.className = "message bot typing"; 
    typingIndicator.textContent = "typing...";
    chatbotMessages.appendChild(typingIndicator);
    chatbotMessages.scrollTop = chatbotMessages.scrollHeight;

    try {
        const result = await chat.sendMessageStream(userMessage);

     
        chatbotMessages.removeChild(typingIndicator);

       
        const botMessageElement = document.createElement("div");
        botMessageElement.className = "message bot"; 
        chatbotMessages.appendChild(botMessageElement);

        
        let responseText = "";
        for await (const chunk of result.stream) {
            const chunkText = chunk.text();
            responseText += chunkText;
            let formattedChunk = responseText.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
            formattedChunk = formattedChunk.replace(/\*(.*?)\*/g, '<em>$1</em>');
            botMessageElement.innerHTML = formattedChunk; 
            chatbotMessages.scrollTop = chatbotMessages.scrollHeight; 
        }

    } catch (error) {
        console.error("Error sending message to Gemini API:", error);
        if (chatbotMessages.contains(typingIndicator)) { 
           chatbotMessages.removeChild(typingIndicator);
        }
         appendSystemMessage(`Sorry, I encountered an error: ${error.message}. Please try again later.`, true); 
    } finally {
       
        if (chatBotInput) chatBotInput.disabled = false;
        if (sendBtn) sendBtn.disabled = false;
        if (chatBotInput) chatBotInput.focus();
    }
}
