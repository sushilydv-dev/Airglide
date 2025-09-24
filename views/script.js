window.addEventListener('pywebviewready', function() {
    document.getElementById("minimize").onclick = function() {
        window.pywebview.api.minimize();
    }

    document.getElementById("close").onclick = function() {
        window.pywebview.api.close();
    }
});
let dragging=false;
let draxOfSet ={x:0,y:0}
const titlebar=document.getElementById('titlebar')
titlebar.addEventListener("mousedown",(e)=>{
    dragging=true;
    draxOfSet.x=e.clientX;
    draxOfSet.y=e.clientY;
})
window.addEventListener("mouseup",()=>{
    dragging=false
})
window.addEventListener("mousemove",(e=>{
    if(dragging){
        let dx = e.clientX - draxOfSet.x;
        let dy = e.clientY - draxOfSet.y;
        window.pywebview.api.move_window(dx, dy);
    }
}))

// adding a new file
window.addEventListener('pywebviewready', function() {
    document.getElementById("uploadPptxButton").onclick = function() {
        window.pywebview.api.fetch_pptx();
    }

});

// camera screen

function cameraFrame(base64Image){
    document.getElementById('camera').src='data:image/jpeg;base64,'+base64Image
}

window.addEventListener("pywebviewready",function(){
  document.getElementById("presentor").onclick=function(){
        window.pywebview.api.presentor()
    }
})


const cameraCheckbox= document.getElementById('camera-checkbox')
const camerascreen = document.getElementById("camera")
cameraCheckbox.addEventListener('change',function(){
    if (cameraCheckbox.checked){
        camerascreen.style.display="block"
        window.pywebview.api.startcamera()
    }
    else{
        camerascreen.style.display="none"
        window.pywebview.api.destroycam()
    }
})

//chatbot

const  chatbotbtn=document.getElementById("chatbot-btn");

chatbotbtn.addEventListener("click",function(){
    window.pywebview.api.openChatBotWindow()
})


//irtual mouse
let mouseRunning = false;  // frontend flag to track the state

function toggleVirtualMouse() {
    if (!mouseRunning) {
        window.pywebview.api.virtual_mouse();  
        
    } else {
        window.pywebview.api.stop_virtual_mouse();  
        
    }
    mouseRunning = !mouseRunning;  // flip the state
}

// camera swithing part
let currentCam = 'lapcam';  // default

function toggleCamera() {
  currentCam = currentCam === 'lapcam' ? 'phonecam' : 'lapcam';
  

  const label = currentCam === 'lapcam' ? 'Laptop Cam' : 'Phone Cam';

  document.getElementById('toggleCamBtn').innerText = `${label}`;

  window.pywebview.api.set_camera(currentCam).then(response => {

    console.log(response);
  });
}

function startGestureControl() {
  window.pywebview.api.start_gesture_control().then(response => {
    console.log(response);
    alert("Gesture control started");
  });
}
