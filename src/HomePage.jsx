import React, { useState } from 'react';

const HomePage = ({ onStartSurvey }) => {
  const [formData, setFormData] = useState({
    companyName: '',
    contactName: '',
    title: '',
    email: '',
    phone: '',
    consent: false
  });

  // 新增：用來追蹤使用者是否碰觸過該欄位（用於離開欄位後才顯示格式錯誤，避免一進來就紅通通）
  const [touched, setTouched] = useState({
    email: false,
    phone: false
  });

  const handleChange = (e) => {
    const { name, value, type, checked } = e.target;
    setFormData(prev => ({
      ...prev,
      [name]: type === 'checkbox' ? checked : value
    }));
  };

  const handleBlur = (e) => {
    const { name } = e.target;
    setTouched(prev => ({ ...prev, [name]: true }));
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!isFormValid) return;
    onStartSurvey(formData);
  };

  // 防呆驗證邏輯
  const isEmailValid = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(formData.email);
  // const isPhoneValid = formData.phone === '' || /^[0-9+\-\s()]{7,15}$/.test(formData.phone);
  const isPhoneValid = formData.phone === '' || /^[0-9+\-\s()#]{7,25}$/.test(formData.phone);

  // 綜合必填與格式是否皆正確[cite: 1]
  const isFormValid = formData.companyName.trim() && 
                      formData.contactName.trim() && 
                      formData.email.trim() && 
                      isEmailValid && 
                      isPhoneValid && 
                      formData.consent;

  return (
    <div className="w-full max-w-md mx-auto px-4 sm:px-0">
      <div className="bg-white rounded-2xl shadow-lg overflow-hidden animate-fade-in-down">
        {/* Header */}
        <div className="bg-gradient-to-r from-slate-700 to-slate-800 px-6 sm:px-8 py-8 sm:py-10 text-center">
          <h1 className="text-2xl sm:text-3xl font-bold text-white mb-2">優樂地永續健檢</h1>
          <p className="text-slate-300 text-sm sm:text-base">請填寫基本資料以開始進行永續健檢</p>
        </div>

        {/* Form Content */}
        <form onSubmit={handleSubmit} className="p-6 sm:p-8 space-y-4">
          <div>
            <label className="block text-sm font-semibold text-slate-700 mb-2">公司名稱 <span className="text-red-500">*</span></label>
            <input 
              type="text" 
              name="companyName" 
              required 
              value={formData.companyName} 
              onChange={handleChange}
              placeholder="例：優樂地永續股份有限公司"
              className="w-full px-4 py-3 sm:py-3.5 border border-slate-300 rounded-lg focus:ring-2 focus:ring-slate-500 focus:border-transparent outline-none transition-all text-base placeholder:text-slate-300" 
            />
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-semibold text-slate-700 mb-2">聯絡人姓名 <span className="text-red-500">*</span></label>
              <input 
                type="text" 
                name="contactName" 
                required 
                value={formData.contactName} 
                onChange={handleChange}
                placeholder="例：王小明"
                className="w-full px-4 py-3 sm:py-3.5 border border-slate-300 rounded-lg focus:ring-2 focus:ring-slate-500 focus:border-transparent outline-none transition-all text-base placeholder:text-slate-300" 
              />
            </div>
            <div>
              <label className="block text-sm font-semibold text-slate-700 mb-2">職稱</label>
              <input 
                type="text" 
                name="title" 
                value={formData.title} 
                onChange={handleChange}
                placeholder="例：永續經理"
                className="w-full px-4 py-3 sm:py-3.5 border border-slate-300 rounded-lg focus:ring-2 focus:ring-slate-500 focus:border-transparent outline-none transition-all text-base placeholder:text-slate-300" 
              />
            </div>
          </div>

          <div>
            <label className="block text-sm font-semibold text-slate-700 mb-2">Email <span className="text-red-500">*</span></label>
            <input 
              type="email" 
              name="email" 
              required 
              value={formData.email} 
              onChange={handleChange}
              onBlur={handleBlur}
              placeholder="name@company.com"
              className="w-full px-4 py-3 sm:py-3.5 border border-slate-300 rounded-lg focus:ring-2 focus:ring-slate-500 focus:border-transparent outline-none transition-all text-base placeholder:text-slate-300" 
            />
            {/* 淺淺的格式提示 */}
            {touched.email && formData.email && !isEmailValid && (
              <p className="mt-1.5 text-xs text-amber-600">請輸入有效的 Email 格式（包含 @）</p>
            )}
          </div>

          <div>
            <label className="block text-sm font-semibold text-slate-700 mb-2">聯絡電話</label>
            <input 
              type="tel" 
              name="phone" 
              value={formData.phone} 
              onChange={handleChange}
              onBlur={handleBlur}
              placeholder="例：0912345678 或 02-12345678"
              className="w-full px-4 py-3 sm:py-3.5 border border-slate-300 rounded-lg focus:ring-2 focus:ring-slate-500 focus:border-transparent outline-none transition-all text-base placeholder:text-slate-300" 
            />
            {touched.phone && formData.phone && !isPhoneValid && (
              <p className="mt-1.5 text-xs text-amber-600">請輸入常規的電話號碼格式</p>
            )}
          </div>

          <div className="pt-2">
            <label className="flex items-start space-x-3 cursor-pointer">
              <input 
                type="checkbox" 
                name="consent" 
                checked={formData.consent} 
                onChange={handleChange} 
                required
                className="mt-1 w-5 h-5 text-slate-600 border-slate-300 rounded focus:ring-slate-500 flex-shrink-0" 
              />
              <span className="text-sm text-slate-600 leading-relaxed font-medium">
                我同意後續由優樂地永續服務股份有限公司聯繫並提供相關服務資訊。<span className="text-red-500">*</span>
              </span>
            </label>
          </div>

          {/* 淺淺的防呆狀態提示：當按鈕不能按時，提示使用者還差什麼 */}
          {/* {!isFormValid && (
            <p className="text-xs text-slate-400 text-center pt-1">
              請完整填寫帶有 <span className="text-red-400">*</span> 的必填欄位並勾選同意條款
            </p>
          )} */}

          <button 
            type="submit" 
            disabled={!isFormValid}
            className={`w-full py-3.5 sm:py-4 rounded-lg font-bold text-base transition-all duration-300 shadow-md mt-2 touch-manipulation
              ${isFormValid 
                ? 'bg-slate-800 text-white hover:bg-slate-700 active:scale-95 cursor-pointer' 
                : 'bg-slate-200 text-slate-400 cursor-not-allowed'}`}
          >
            開始健檢
          </button>
        </form>
      </div>
    </div>
  );
};

export default HomePage;