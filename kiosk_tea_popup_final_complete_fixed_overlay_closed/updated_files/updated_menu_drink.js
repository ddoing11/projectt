
// 팝업을 닫는 함수 추가
function closePopup() {
  const popup = document.querySelector('.popup-overlay');
  if (popup) {
    popup.remove();
  }
}

// 옵션 선택 완료 후 팝업을 닫는 이벤트 추가
document.getElementById('complete-selection').addEventListener('click', function() {
  // 옵션 선택 로직 처리 후 팝업 닫기
  closePopup();
});
