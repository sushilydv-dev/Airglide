function showNotification(message){
    const note = document.getElementById("notification")
    note.innerText=message
    note.style.display="block"
    setTimeout(()=>{
        note.style.display="none"
    },2000)
    }
window.showNotification=showNotification