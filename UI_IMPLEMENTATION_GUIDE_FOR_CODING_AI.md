# Детальные инструкции по реализации интерфейса Personal AI Hub для coding-агента

## Назначение документа

Этот файл предназначен для LLM, занимающейся написанием кода интерфейса приложения Personal AI Hub. Он содержит детальные инструкции по созданию **максимально приятного, функционального и безопасного** интерфейса на основе актуальных практик 2026 года.

**Ключевое требование:** интерфейс должен подчёркивать уникальность продукта — **контроль расходов, приватность данных и локальность обработки**. Это не просто чат, это AI-хаб с экономической и информационной дисциплиной.

---

## Контекст проекта

### Текущий стек
- **Frontend:** Next.js 16 + React 19 + TypeScript
- **Styling:** Tailwind CSS (в процессе миграции на семантические токены)
- **Компоненты:** базовые, без дизайн-системы (требуется внедрение shadcn/ui)
- **State:** React Context + `localStorage` для токена
- **API Client:** `lib/api.ts` с авторизацией через Bearer-токен

### Что уже работает
- авторизация (login/logout);
- страницы: `/chat`, `/providers`, `/models`, `/usage`, `/knowledge`, `/tables`, `/jobs`;
- базовый чат со streaming через SSE;
- провайдеры и модели (список, sync);
- usage records;
- загрузка файлов.

### Что отсутствует и требуется
- дизайн-система;
- онбординг;
- профиль пользователя;
- индикаторы приватности и стоимости в чате;
- reasoning depth селектор;
- веб-доступ;
- локальный режим;
- состояния пустоты (empty states);
- клавиатурная навигация;
- доступность (accessibility).

---

## 1. Дизайн-система и токены

### 1.1. Выбор: shadcn/ui + Radix + Tailwind

**Обоснование:**
- shadcn/ui — это не библиотека, а набор копируемых компонентов, что даёт полный контроль;
- Radix UI даёт accessibility из коробки;
- Tailwind уже используется;
- совместим с Next.js App Router и SSR.

**Установка:**

```bash
npx shadcn@latest init
```

При инициализации выбрать:
- стиль: `Default`
- цвета: `Slate`
- CSS-переменные: `Yes`
- путь компонентов: `apps/web/components/ui`

**Результат:** создаётся `components.json`, файл `globals.css` с CSS-переменными, утилита `lib/utils.ts` с `cn()`.

### 1.2. Семантические токены (Design Tokens)

Вместо прямого использования `bg-slate-700` использовать семантические токены через CSS-переменные.

**Создать файл `apps/web/styles/tokens.css`:**

```css
@layer base {
  :root {
    /* Spacing */
    --spacing-xs: 0.25rem;    /* 4px */
    --spacing-sm: 0.5rem;     /* 8px */
    --spacing-md: 0.75rem;    /* 12px */
    --spacing-base: 1rem;     /* 16px */
    --spacing-lg: 1.5rem;     /* 24px */
    --spacing-xl: 2rem;       /* 32px */
    --spacing-2xl: 3rem;      /* 48px */
    --spacing-3xl: 4rem;      /* 64px */

    /* Border radius */
    --radius-sm: 0.375rem;    /* 6px */
    --radius-md: 0.625rem;    /* 10px */
    --radius-lg: 0.875rem;    /* 14px */
    --radius-xl: 1.25rem;     /* 20px */
    --radius-full: 9999px;

    /* Typography scale */
    --text-xs: 0.75rem;       /* 12px */
    --text-sm: 0.8125rem;     /* 13px */
    --text-base: 0.875rem;    /* 14px */
    --text-lg: 1rem;          /* 16px */
    --text-xl: 1.25rem;       /* 20px */
    --text-2xl: 1.5rem;       /* 24px */
    --text-3xl: 1.875rem;     /* 30px */

    /* Semantic colors (light mode) */
    --background: 0 0% 100%;
    --foreground: 222.2 84% 4.9%;
    
    --card: 0 0% 100%;
    --card-foreground: 222.2 84% 4.9%;
    
    --popover: 0 0% 100%;
    --popover-foreground: 222.2 84% 4.9%;
    
    --primary: 221.2 83.2% 53.3%;
    --primary-foreground: 210 40% 98%;
    
    --secondary: 210 40% 96.1%;
    --secondary-foreground: 222.2 47.4% 11.2%;
    
    --muted: 210 40% 96.1%;
    --muted-foreground: 215.4 16.3% 46.9%;
    
    --accent: 210 40% 96.1%;
    --accent-foreground: 222.2 47.4% 11.2%;
    
    --destructive: 0 84.2% 60.2%;
    --destructive-foreground: 210 40% 98%;

    --success: 142 71% 45%;
    --success-foreground: 210 40% 98%;

    --warning: 38 92% 50%;
    --warning-foreground: 222.2 84% 4.9%;

    --info: 199 89% 48%;
    --info-foreground: 210 40% 98%;
    
    --border: 214.3 31.8% 91.4%;
    --input: 214.3 31.8% 91.4%;
    --ring: 221.2 83.2% 53.3%;
    
    /* Приватность и локальность */
    --local-mode: 142 71% 45%;         /* зелёный для локального */
    --cloud-mode: 199 89% 48%;         /* голубой для облака */
    --privacy-badge: 142 71% 45%;
    --privacy-badge-foreground: 210 40% 98%;

    /* Стоимость */
    --cost-low: 142 71% 45%;           /* дешёвый запрос */
    --cost-medium: 38 92% 50%;         /* средний */
    --cost-high: 0 84.2% 60.2%;        /* дорогой */
    --cost-unknown: 215.4 16.3% 46.9%; /* без цены */
  }

  .dark {
    --background: 222.2 84% 4.9%;
    --foreground: 210 40% 98%;
    
    --card: 222.2 84% 4.9%;
    --card-foreground: 210 40% 98%;
    
    --popover: 222.2 84% 4.9%;
    --popover-foreground: 210 40% 98%;
    
    --primary: 217.2 91.2% 59.8%;
    --primary-foreground: 222.2 47.4% 11.2%;
    
    --secondary: 217.2 32.6% 17.5%;
    --secondary-foreground: 210 40% 98%;
    
    --muted: 217.2 32.6% 17.5%;
    --muted-foreground: 215 20.2% 65.1%;
    
    --accent: 217.2 32.6% 17.5%;
    --accent-foreground: 210 40% 98%;
    
    --destructive: 0 62.8% 30.6%;
    --destructive-foreground: 210 40% 98%;

    --success: 142 71% 45%;
    --success-foreground: 210 40% 98%;

    --warning: 38 92% 50%;
    --warning-foreground: 222.2 84% 4.9%;

    --info: 199 89% 48%;
    --info-foreground: 210 40% 98%;
    
    --border: 217.2 32.6% 17.5%;
    --input: 217.2 32.6% 17.5%;
    --ring: 224.3 76.3% 48%;

    --local-mode: 142 71% 45%;
    --cloud-mode: 199 89% 48%;
    --privacy-badge: 142 71% 45%;
    --privacy-badge-foreground: 222.2 84% 4.9%;

    --cost-low: 142 71% 45%;
    --cost-medium: 38 92% 50%;
    --cost-high: 0 84.2% 60.2%;
    --cost-unknown: 215 20.2% 65.1%;
  }
}
```

**Импортировать в `globals.css`:**

```css
@import './tokens.css';
```

**Расширить `tailwind.config.ts`:**

```typescript
extend: {
  colors: {
    'local-mode': 'hsl(var(--local-mode))',
    'cloud-mode': 'hsl(var(--cloud-mode))',
    'privacy-badge': 'hsl(var(--privacy-badge))',
    'privacy-badge-foreground': 'hsl(var(--privacy-badge-foreground))',
    'cost-low': 'hsl(var(--cost-low))',
    'cost-medium': 'hsl(var(--cost-medium))',
    'cost-high': 'hsl(var(--cost-high))',
    'cost-unknown': 'hsl(var(--cost-unknown))',
  },
  spacing: {
    'xs': 'var(--spacing-xs)',
    'sm': 'var(--spacing-sm)',
    'md': 'var(--spacing-md)',
    'base': 'var(--spacing-base)',
    'lg': 'var(--spacing-lg)',
    'xl': 'var(--spacing-xl)',
    '2xl': 'var(--spacing-2xl)',
    '3xl': 'var(--spacing-3xl)',
  },
  borderRadius: {
    'sm': 'var(--radius-sm)',
    'md': 'var(--radius-md)',
    'lg': 'var(--radius-lg)',
    'xl': 'var(--radius-xl)',
  }
}
```

### 1.3. Контрастность и WCAG AA

**Все цвета проверены на соответствие WCAG AA (минимум 4.5:1 для текста).**

Единственное исключение: `--success` на белом фоне даёт 3.30:1. Для использования success в бейджах:
- либо использовать на тёмном фоне;
- либо добавить обводку `ring-1 ring-green-700`;
- либо применять только для крупных элементов (заголовки), где требование 3:1.

---

## 2. Базовые компоненты

### 2.1. Установить ключевые shadcn/ui компоненты

```bash
npx shadcn@latest add button
npx shadcn@latest add input
npx shadcn@latest add label
npx shadcn@latest add card
npx shadcn@latest add badge
npx shadcn@latest add alert
npx shadcn@latest add dialog
npx shadcn@latest add dropdown-menu
npx shadcn@latest add select
npx shadcn@latest add switch
npx shadcn@latest add tabs
npx shadcn@latest add toast
npx shadcn@latest add tooltip
npx shadcn@latest add skeleton
npx shadcn@latest add progress
npx shadcn@latest add separator
npx shadcn@latest add avatar
npx shadcn@latest add command
```

### 2.2. Кастомный компонент: PrivacyBadge

Показывает, локально или через облако обрабатывался запрос.

**Создать `apps/web/components/ui/privacy-badge.tsx`:**

```typescript
import { Badge } from '@/components/ui/badge';
import { Shield, Cloud } from 'lucide-react';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';

interface PrivacyBadgeProps {
  mode: 'local' | 'cloud';
  size?: 'sm' | 'md';
}

export function PrivacyBadge({ mode, size = 'md' }: PrivacyBadgeProps) {
  const isLocal = mode === 'local';
  const Icon = isLocal ? Shield : Cloud;
  const text = isLocal ? 'Локально' : 'Облако';
  const tooltip = isLocal 
    ? 'Данные обработаны на вашем компьютере и не отправлялись во внешние сервисы' 
    : 'Запрос отправлен во внешний AI-провайдер';

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <Badge
            variant={isLocal ? 'default' : 'secondary'}
            className={cn(
              'gap-1 font-medium cursor-help',
              isLocal && 'bg-privacy-badge text-privacy-badge-foreground hover:bg-privacy-badge/90',
              size === 'sm' && 'text-xs px-1.5 py-0.5'
            )}
          >
            <Icon className={size === 'sm' ? 'h-3 w-3' : 'h-3.5 w-3.5'} />
            {text}
          </Badge>
        </TooltipTrigger>
        <TooltipContent>
          <p className="max-w-xs">{tooltip}</p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
```

### 2.3. Кастомный компонент: CostBadge

Показывает стоимость запроса.

**Создать `apps/web/components/ui/cost-badge.tsx`:**

```typescript
import { Badge } from '@/components/ui/badge';
import { DollarSign, HelpCircle } from 'lucide-react';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';

interface CostBadgeProps {
  cost?: number;        // в рублях
  currency?: string;    // по умолчанию '₽'
  status?: 'estimated' | 'actual' | 'unknown';
  tokensIn?: number;
  tokensOut?: number;
  size?: 'sm' | 'md';
}

export function CostBadge({ 
  cost, 
  currency = '₽', 
  status = 'actual',
  tokensIn,
  tokensOut,
  size = 'md'
}: CostBadgeProps) {
  if (status === 'unknown' || cost === undefined) {
    return (
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <Badge
              variant="outline"
              className={cn(
                'gap-1 text-cost-unknown border-cost-unknown cursor-help',
                size === 'sm' && 'text-xs px-1.5 py-0.5'
              )}
            >
              <HelpCircle className={size === 'sm' ? 'h-3 w-3' : 'h-3.5 w-3.5'} />
              Цена не задана
            </Badge>
          </TooltipTrigger>
          <TooltipContent>
            <p>Для этой модели не настроена стоимость.<br/>Запрос не учитывается в бюджете.</p>
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    );
  }

  const costColor = cost < 1 ? 'cost-low' : cost < 10 ? 'cost-medium' : 'cost-high';
  const isEstimated = status === 'estimated';

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <Badge
            variant="outline"
            className={cn(
              'gap-1 font-medium cursor-help',
              `text-${costColor} border-${costColor}`,
              isEstimated && 'border-dashed',
              size === 'sm' && 'text-xs px-1.5 py-0.5'
            )}
          >
            <DollarSign className={size === 'sm' ? 'h-3 w-3' : 'h-3.5 w-3.5'} />
            {isEstimated && '≈'}
            {cost.toFixed(2)} {currency}
          </Badge>
        </TooltipTrigger>
        <TooltipContent>
          <div className="text-sm">
            <p className="font-medium mb-1">{isEstimated ? 'Оценка' : 'Фактическая стоимость'}</p>
            {tokensIn !== undefined && <p>Вход: {tokensIn.toLocaleString()} токенов</p>}
            {tokensOut !== undefined && <p>Выход: {tokensOut.toLocaleString()} токенов</p>}
            {isEstimated && <p className="text-muted-foreground mt-1 text-xs">Точная стоимость будет доступна после завершения</p>}
          </div>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
```

### 2.4. Кастомный компонент: ModelPricingWarning

Показывает предупреждение при выборе модели без цены.

**Создать `apps/web/components/ui/model-pricing-warning.tsx`:**

```typescript
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { AlertTriangle } from 'lucide-react';
import { Button } from '@/components/ui/button';

interface ModelPricingWarningProps {
  modelName: string;
  onSetupPrice?: () => void;
  onDismiss?: () => void;
  variant?: 'inline' | 'toast';
}

export function ModelPricingWarning({ 
  modelName, 
  onSetupPrice, 
  onDismiss,
  variant = 'inline'
}: ModelPricingWarningProps) {
  if (variant === 'toast') {
    // Для toast-версии возвращаем только текст
    return {
      title: 'Модель без настроенной цены',
      description: `${modelName} работает, но стоимость не будет учитываться в бюджете.`,
    };
  }

  return (
    <Alert variant="warning" className="border-warning/50">
      <AlertTriangle className="h-4 w-4" />
      <AlertTitle>Цена не настроена</AlertTitle>
      <AlertDescription className="mt-2 space-y-2">
        <p>
          Модель <strong>{modelName}</strong> будет работать, но:
        </p>
        <ul className="list-disc list-inside text-sm space-y-1 text-muted-foreground">
          <li>Стоимость запросов не будет рассчитываться</li>
          <li>Запросы не войдут в отчёты по бюджету</li>
          <li>Лимиты расходов не будут работать</li>
        </ul>
        <div className="flex gap-2 mt-3">
          {onSetupPrice && (
            <Button size="sm" onClick={onSetupPrice}>
              Настроить цену
            </Button>
          )}
          {onDismiss && (
            <Button size="sm" variant="ghost" onClick={onDismiss}>
              Понятно, продолжить
            </Button>
          )}
        </div>
      </AlertDescription>
    </Alert>
  );
}
```

---

## 3. Онбординг (Onboarding)

### 3.1. Цели онбординга

- провести пользователя от пустого состояния до первого успешного запроса;
- показать ценность: контроль расходов + приватность;
- не перегружать: 4–5 шагов максимум.

### 3.2. Структура wizard

**Шаги:**
1. Добавить провайдера (выбор из presets или custom);
2. Проверить ключ (health check);
3. Синхронизировать модели;
4. Установить бюджет (опционально, можно пропустить);
5. Отправить тестовое сообщение.

**Создать `apps/web/components/onboarding/onboarding-wizard.tsx`:**

```typescript
'use client';

import { useState } from 'react';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import { CheckCircle2 } from 'lucide-react';
import { AddProviderStep } from './steps/add-provider-step';
import { SyncModelsStep } from './steps/sync-models-step';
import { SetBudgetStep } from './steps/set-budget-step';
import { FirstMessageStep } from './steps/first-message-step';

const STEPS = [
  { id: 'provider', title: 'Добавить провайдера', component: AddProviderStep },
  { id: 'models', title: 'Синхронизировать модели', component: SyncModelsStep },
  { id: 'budget', title: 'Настроить бюджет', component: SetBudgetStep, optional: true },
  { id: 'first-message', title: 'Первый запрос', component: FirstMessageStep },
];

interface OnboardingWizardProps {
  open: boolean;
  onComplete: () => void;
}

export function OnboardingWizard({ open, onComplete }: OnboardingWizardProps) {
  const [currentStep, setCurrentStep] = useState(0);
  const [completedSteps, setCompletedSteps] = useState<Set<string>>(new Set());

  const step = STEPS[currentStep];
  const StepComponent = step.component;
  const progress = ((currentStep + 1) / STEPS.length) * 100;

  const handleNext = () => {
    setCompletedSteps(prev => new Set(prev).add(step.id));
    if (currentStep < STEPS.length - 1) {
      setCurrentStep(prev => prev + 1);
    } else {
      onComplete();
    }
  };

  const handleSkip = () => {
    if (step.optional) {
      handleNext();
    }
  };

  return (
    <Dialog open={open} onOpenChange={() => {}}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto" hideClose>
        <DialogHeader>
          <DialogTitle className="text-2xl">Добро пожаловать в Personal AI Hub</DialogTitle>
          <DialogDescription>
            Настроим ваш AI-хаб за несколько шагов. Это займёт 2–3 минуты.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-6 py-4">
          {/* Progress */}
          <div className="space-y-2">
            <div className="flex justify-between text-sm text-muted-foreground">
              <span>Шаг {currentStep + 1} из {STEPS.length}</span>
              <span>{Math.round(progress)}%</span>
            </div>
            <Progress value={progress} className="h-2" />
          </div>

          {/* Steps indicator */}
          <div className="flex justify-between">
            {STEPS.map((s, idx) => (
              <div key={s.id} className="flex items-center gap-2">
                <div
                  className={cn(
                    'flex h-8 w-8 items-center justify-center rounded-full border-2',
                    completedSteps.has(s.id)
                      ? 'border-primary bg-primary text-primary-foreground'
                      : idx === currentStep
                      ? 'border-primary text-primary'
                      : 'border-muted text-muted-foreground'
                  )}
                >
                  {completedSteps.has(s.id) ? (
                    <CheckCircle2 className="h-5 w-5" />
                  ) : (
                    <span className="text-sm font-medium">{idx + 1}</span>
                  )}
                </div>
                {idx < STEPS.length - 1 && (
                  <div className="h-0.5 w-12 bg-muted" />
                )}
              </div>
            ))}
          </div>

          {/* Current step content */}
          <div className="border rounded-lg p-6 bg-card">
            <h3 className="text-lg font-semibold mb-4">{step.title}</h3>
            <StepComponent onNext={handleNext} onSkip={step.optional ? handleSkip : undefined} />
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
```

**Показывать wizard при первом входе:**

В `apps/web/app/page.tsx` или `layout.tsx` проверять флаг `onboarding_completed` в `localStorage` и показывать `<OnboardingWizard />`.

---

## 4. Экран чата: полный редизайн

### 4.1. Структура страницы `/chat/[id]`

**Левая панель (sidebar):**
- список диалогов (virtualized, если много);
- кнопка "Новый чат";
- фильтр по дате/провайдеру/стоимости.

**Центральная область:**
- заголовок с названием диалога (editable);
- список сообщений (virtualized через `react-virtuoso`);
- форма ввода с:
  - селектором модели;
  - индикатором reasoning depth;
  - тумблером локального режима;
  - тумблером веб-доступа;
  - кнопкой прикрепления файлов;
  - индикатором оставшегося бюджета.

**Правая панель (опциональная, toggle):**
- инспектор текущего сообщения:
  - приватность (локально/облако);
  - стоимость (estimated/actual);
  - токены (in/out);
  - reasoning tokens;
  - источники (если есть веб-доступ или RAG);
  - полный JSON (developer mode).

### 4.2. Виртуализация списка сообщений

Для длинных чатов (>100 сообщений) использовать **react-virtuoso**:

```bash
npm install react-virtuoso
```

**Пример использования в `apps/web/components/chat/message-list.tsx`:**

```typescript
import { Virtuoso } from 'react-virtuoso';
import { Message } from './message';

interface MessageListProps {
  messages: Message[];
}

export function MessageList({ messages }: MessageListProps) {
  return (
    <Virtuoso
      data={messages}
      className="flex-1"
      followOutput="smooth"
      itemContent={(index, message) => (
        <Message key={message.id} message={message} />
      )}
      components={{
        Footer: () => <div className="h-4" />, // spacing at bottom
      }}
    />
  );
}
```

### 4.3. Компонент сообщения с индикаторами

**Создать `apps/web/components/chat/message.tsx`:**

```typescript
'use client';

import { useState } from 'react';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Copy, RefreshCw, ThumbsUp, ThumbsDown, MoreVertical } from 'lucide-react';
import { PrivacyBadge } from '@/components/ui/privacy-badge';
import { CostBadge } from '@/components/ui/cost-badge';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { MarkdownRenderer } from './markdown-renderer';
import { cn } from '@/lib/utils';

interface MessageProps {
  message: {
    id: string;
    role: 'user' | 'assistant';
    content: string;
    privacy?: 'local' | 'cloud';
    cost?: number;
    costStatus?: 'estimated' | 'actual' | 'unknown';
    tokensIn?: number;
    tokensOut?: number;
    reasoningTokens?: number;
    sources?: Array<{ title: string; url: string; snippet: string }>;
    timestamp: Date;
  };
  onRegenerate?: () => void;
  onCopy?: () => void;
  onFeedback?: (type: 'up' | 'down') => void;
}

export function Message({ message, onRegenerate, onCopy, onFeedback }: MessageProps) {
  const [showActions, setShowActions] = useState(false);
  const isUser = message.role === 'user';

  return (
    <div
      className={cn(
        'group px-4 py-6 hover:bg-accent/50 transition-colors',
        isUser && 'bg-muted/30'
      )}
      onMouseEnter={() => setShowActions(true)}
      onMouseLeave={() => setShowActions(false)}
    >
      <div className="max-w-3xl mx-auto flex gap-4">
        {/* Avatar */}
        <div className={cn(
          'flex h-8 w-8 shrink-0 select-none items-center justify-center rounded-md border',
          isUser ? 'bg-background' : 'bg-primary text-primary-foreground'
        )}>
          {isUser ? '👤' : '🤖'}
        </div>

        {/* Content */}
        <div className="flex-1 space-y-2 overflow-hidden">
          <MarkdownRenderer content={message.content} />

          {/* Sources (если есть) */}
          {message.sources && message.sources.length > 0 && (
            <div className="mt-3 space-y-2">
              <p className="text-sm font-medium text-muted-foreground">Источники:</p>
              <div className="grid gap-2">
                {message.sources.map((source, idx) => (
                  <a
                    key={idx}
                    href={source.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="block rounded-lg border p-3 hover:bg-accent transition-colors"
                  >
                    <div className="flex items-start gap-2">
                      <span className="flex h-5 w-5 items-center justify-center rounded bg-primary/10 text-xs font-medium text-primary">
                        {idx + 1}
                      </span>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium truncate">{source.title}</p>
                        <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2">{source.snippet}</p>
                      </div>
                    </div>
                  </a>
                ))}
              </div>
            </div>
          )}

          {/* Badges */}
          {!isUser && (
            <div className="flex flex-wrap gap-2 mt-3">
              {message.privacy && <PrivacyBadge mode={message.privacy} size="sm" />}
              <CostBadge
                cost={message.cost}
                status={message.costStatus}
                tokensIn={message.tokensIn}
                tokensOut={message.tokensOut}
                size="sm"
              />
              {message.reasoningTokens && message.reasoningTokens > 0 && (
                <Badge variant="outline" className="text-xs">
                  🧠 {message.reasoningTokens.toLocaleString()} reasoning
                </Badge>
              )}
            </div>
          )}
        </div>

        {/* Actions */}
        {!isUser && (
          <div className={cn(
            'flex gap-1 opacity-0 transition-opacity',
            showActions && 'opacity-100'
          )}>
            <Button size="icon" variant="ghost" onClick={onCopy}>
              <Copy className="h-4 w-4" />
            </Button>
            {onRegenerate && (
              <Button size="icon" variant="ghost" onClick={onRegenerate}>
                <RefreshCw className="h-4 w-4" />
              </Button>
            )}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button size="icon" variant="ghost">
                  <MoreVertical className="h-4 w-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onClick={() => onFeedback?.('up')}>
                  <ThumbsUp className="mr-2 h-4 w-4" />
                  Полезно
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => onFeedback?.('down')}>
                  <ThumbsDown className="mr-2 h-4 w-4" />
                  Не помогло
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        )}
      </div>
    </div>
  );
}
```

### 4.4. Markdown-рендеринг с подсветкой кода

Использовать **react-markdown** + **shiki** для подсветки:

```bash
npm install react-markdown rehype-raw remark-gfm shiki
```

**Создать `apps/web/components/chat/markdown-renderer.tsx`:**

```typescript
'use client';

import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeRaw from 'rehype-raw';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/cjs/styles/prism';
import { Button } from '@/components/ui/button';
import { Check, Copy } from 'lucide-react';
import { useState } from 'react';

interface CodeBlockProps {
  inline?: boolean;
  className?: string;
  children: React.ReactNode;
}

function CodeBlock({ inline, className, children, ...props }: CodeBlockProps) {
  const [copied, setCopied] = useState(false);
  const match = /language-(\w+)/.exec(className || '');
  const lang = match ? match[1] : '';
  const code = String(children).replace(/\n$/, '');

  const handleCopy = async () => {
    await navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  if (inline) {
    return (
      <code className="rounded bg-muted px-1 py-0.5 font-mono text-sm" {...props}>
        {children}
      </code>
    );
  }

  return (
    <div className="relative group">
      <Button
        size="icon"
        variant="ghost"
        className="absolute right-2 top-2 h-8 w-8 opacity-0 group-hover:opacity-100 transition-opacity"
        onClick={handleCopy}
      >
        {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
      </Button>
      <SyntaxHighlighter
        style={vscDarkPlus}
        language={lang || 'text'}
        PreTag="div"
        className="!mt-0 rounded-lg text-sm"
        {...props}
      >
        {code}
      </SyntaxHighlighter>
    </div>
  );
}

interface MarkdownRendererProps {
  content: string;
}

export function MarkdownRenderer({ content }: MarkdownRendererProps) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      rehypePlugins={[rehypeRaw]}
      components={{
        code: CodeBlock,
        a: ({ href, children }) => (
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            className="text-primary underline-offset-4 hover:underline"
          >
            {children}
          </a>
        ),
        table: ({ children }) => (
          <div className="my-4 overflow-x-auto">
            <table className="w-full border-collapse border">{children}</table>
          </div>
        ),
        th: ({ children }) => (
          <th className="border bg-muted px-4 py-2 text-left font-medium">{children}</th>
        ),
        td: ({ children }) => (
          <td className="border px-4 py-2">{children}</td>
        ),
      }}
      className="prose prose-slate dark:prose-invert max-w-none"
    >
      {content}
    </ReactMarkdown>
  );
}
```

### 4.5. Форма ввода с селекторами

**Создать `apps/web/components/chat/chat-input.tsx`:**

```typescript
'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { Label } from '@/components/ui/label';
import { Paperclip, Send, StopCircle, Shield, Globe } from 'lucide-react';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Separator } from '@/components/ui/separator';
import { Badge } from '@/components/ui/badge';
import { ModelPricingWarning } from '@/components/ui/model-pricing-warning';

interface ChatInputProps {
  models: Array<{ id: string; name: string; hasPrice: boolean }>;
  selectedModel?: string;
  onModelChange: (modelId: string) => void;
  onSend: (message: string, options: {
    reasoningDepth?: 'low' | 'medium' | 'high';
    localMode: boolean;
    webAccess: boolean;
  }) => void;
  onStop?: () => void;
  isStreaming?: boolean;
  remainingBudget?: { daily: number; monthly: number; currency: string };
}

export function ChatInput({
  models,
  selectedModel,
  onModelChange,
  onSend,
  onStop,
  isStreaming,
  remainingBudget,
}: ChatInputProps) {
  const [message, setMessage] = useState('');
  const [localMode, setLocalMode] = useState(false);
  const [webAccess, setWebAccess] = useState(false);
  const [reasoningDepth, setReasoningDepth] = useState<'low' | 'medium' | 'high'>('medium');

  const selectedModelData = models.find(m => m.id === selectedModel);
  const showPricingWarning = selectedModelData && !selectedModelData.hasPrice;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!message.trim() || isStreaming) return;

    onSend(message, { reasoningDepth, localMode, webAccess });
    setMessage('');
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.ctrlKey && !e.metaKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  return (
    <div className="border-t bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="max-w-3xl mx-auto p-4 space-y-3">
        {/* Pricing warning */}
        {showPricingWarning && (
          <ModelPricingWarning
            modelName={selectedModelData.name}
            onSetupPrice={() => {/* navigate to models page */}}
          />
        )}

        {/* Controls row */}
        <div className="flex flex-wrap items-center gap-3">
          {/* Model selector */}
          <Select value={selectedModel} onValueChange={onModelChange}>
            <SelectTrigger className="w-[240px]">
              <SelectValue placeholder="Выбрать модель" />
            </SelectTrigger>
            <SelectContent>
              {models.map(model => (
                <SelectItem key={model.id} value={model.id}>
                  <div className="flex items-center gap-2">
                    <span>{model.name}</span>
                    {!model.hasPrice && (
                      <Badge variant="outline" className="text-xs">Без цены</Badge>
                    )}
                  </div>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          {/* Reasoning depth */}
          <Popover>
            <PopoverTrigger asChild>
              <Button variant="outline" size="sm">
                🧠 Глубина: {reasoningDepth === 'low' ? 'Низкая' : reasoningDepth === 'medium' ? 'Средняя' : 'Высокая'}
              </Button>
            </PopoverTrigger>
            <PopoverContent className="w-80">
              <div className="space-y-3">
                <h4 className="font-medium">Глубина размышления</h4>
                <p className="text-sm text-muted-foreground">
                  Влияет на качество ответа и стоимость запроса
                </p>
                <Separator />
                {['low', 'medium', 'high'].map(depth => (
                  <button
                    key={depth}
                    onClick={() => setReasoningDepth(depth as any)}
                    className={cn(
                      'w-full text-left p-3 rounded-lg border transition-colors',
                      reasoningDepth === depth
                        ? 'border-primary bg-primary/5'
                        : 'border-transparent hover:bg-accent'
                    )}
                  >
                    <div className="font-medium capitalize">{depth === 'low' ? 'Низкая' : depth === 'medium' ? 'Средняя' : 'Высокая'}</div>
                    <div className="text-sm text-muted-foreground mt-1">
                      {depth === 'low' && 'Быстрые ответы, минимальная стоимость'}
                      {depth === 'medium' && 'Баланс качества и стоимости'}
                      {depth === 'high' && 'Максимальное качество, выше стоимость'}
                    </div>
                  </button>
                ))}
              </div>
            </PopoverContent>
          </Popover>

          {/* Local mode */}
          <div className="flex items-center gap-2">
            <Switch
              id="local-mode"
              checked={localMode}
              onCheckedChange={setLocalMode}
            />
            <Label htmlFor="local-mode" className="flex items-center gap-1 cursor-pointer">
              <Shield className="h-4 w-4" />
              Локально
            </Label>
          </div>

          {/* Web access */}
          <div className="flex items-center gap-2">
            <Switch
              id="web-access"
              checked={webAccess}
              onCheckedChange={setWebAccess}
            />
            <Label htmlFor="web-access" className="flex items-center gap-1 cursor-pointer">
              <Globe className="h-4 w-4" />
              Веб
            </Label>
          </div>

          {/* Remaining budget */}
          {remainingBudget && (
            <div className="ml-auto text-sm text-muted-foreground">
              Осталось: {remainingBudget.daily.toFixed(2)} {remainingBudget.currency} сегодня
            </div>
          )}
        </div>

        {/* Input form */}
        <form onSubmit={handleSubmit} className="relative">
          <Textarea
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Напишите сообщение... (Enter для отправки, Shift+Enter для новой строки)"
            className="min-h-[80px] pr-24 resize-none"
            disabled={isStreaming}
          />
          <div className="absolute bottom-2 right-2 flex gap-2">
            <Button type="button" size="icon" variant="ghost">
              <Paperclip className="h-4 w-4" />
            </Button>
            {isStreaming ? (
              <Button type="button" size="icon" variant="destructive" onClick={onStop}>
                <StopCircle className="h-4 w-4" />
              </Button>
            ) : (
              <Button type="submit" size="icon" disabled={!message.trim()}>
                <Send className="h-4 w-4" />
              </Button>
            )}
          </div>
        </form>
      </div>
    </div>
  );
}
```

---

## 5. Профиль пользователя

### 5.1. Страница `/profile`

**Разделы:**
- Основная информация (email, дата регистрации);
- Смена пароля;
- API-токены (генерация, список, удаление);
- Настройки локализации;
- Экспорт данных.

**Создать `apps/web/app/profile/page.tsx`:**

```typescript
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { ChangePasswordForm } from '@/components/profile/change-password-form';
import { ApiTokensSection } from '@/components/profile/api-tokens-section';
import { ExportDataSection } from '@/components/profile/export-data-section';

export default async function ProfilePage() {
  // Загрузить данные пользователя через API
  const user = await getCurrentUser();

  return (
    <div className="container max-w-4xl py-8 space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Профиль</h1>
        <p className="text-muted-foreground mt-2">
          Управление учётной записью и настройками
        </p>
      </div>

      {/* Основная информация */}
      <Card>
        <CardHeader>
          <CardTitle>Учётная запись</CardTitle>
          <CardDescription>Основная информация о пользователе</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div>
            <Label className="text-sm font-medium">Email</Label>
            <p className="text-sm text-muted-foreground">{user.email}</p>
          </div>
          <div>
            <Label className="text-sm font-medium">Дата регистрации</Label>
            <p className="text-sm text-muted-foreground">
              {new Date(user.createdAt).toLocaleDateString('ru-RU')}
            </p>
          </div>
        </CardContent>
      </Card>

      {/* Смена пароля */}
      <Card>
        <CardHeader>
          <CardTitle>Смена пароля</CardTitle>
          <CardDescription>Обновить пароль для входа</CardDescription>
        </CardHeader>
        <CardContent>
          <ChangePasswordForm />
        </CardContent>
      </Card>

      {/* API токены */}
      <ApiTokensSection />

      {/* Экспорт данных */}
      <ExportDataSection />
    </div>
  );
}
```

---

## 6. Empty States

### 6.1. Принципы

- Показывать, что делать дальше;
- Объяснять, зачем это нужно;
- Давать пример результата (screenshot/illustration).

### 6.2. Пример: Empty state для чатов

**Создать `apps/web/components/chat/empty-chat-state.tsx`:**

```typescript
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { MessageSquarePlus, Sparkles } from 'lucide-react';

interface EmptyChatStateProps {
  onNewChat: () => void;
}

export function EmptyChatState({ onNewChat }: EmptyChatStateProps) {
  const examples = [
    'Проанализируй файл sales.xlsx и покажи топ-5 продуктов',
    'Найди информацию о новых законах по налогам',
    'Напиши письмо клиенту с извинениями за задержку',
  ];

  return (
    <div className="flex flex-col items-center justify-center h-full p-8 text-center">
      <div className="w-16 h-16 rounded-full bg-primary/10 flex items-center justify-center mb-4">
        <Sparkles className="w-8 h-8 text-primary" />
      </div>
      
      <h2 className="text-2xl font-semibold mb-2">Начните новый диалог</h2>
      <p className="text-muted-foreground mb-8 max-w-md">
        Задайте вопрос, загрузите файл или выберите один из примеров ниже
      </p>

      <div className="grid gap-3 w-full max-w-2xl mb-8">
        {examples.map((example, idx) => (
          <Card
            key={idx}
            className="p-4 cursor-pointer hover:bg-accent transition-colors text-left"
            onClick={() => {/* use example */}}
          >
            <p className="text-sm">{example}</p>
          </Card>
        ))}
      </div>

      <Button size="lg" onClick={onNewChat}>
        <MessageSquarePlus className="mr-2 h-5 w-5" />
        Новый чат
      </Button>
    </div>
  );
}
```

---

## 7. Доступность (Accessibility)

### 7.1. ARIA-атрибуты для streaming

**При стриминге:**
- `aria-live="off"` на контейнере сообщения во время токенов;
- после завершения переключить `aria-live="polite"` и обновить `aria-label`.

**Пример в `Message` компоненте:**

```typescript
const [ariaLive, setAriaLive] = useState<'off' | 'polite'>('off');

useEffect(() => {
  if (message.isComplete) {
    setAriaLive('polite');
  }
}, [message.isComplete]);

return (
  <div
    role="article"
    aria-live={ariaLive}
    aria-label={`Сообщение от ${isUser ? 'вас' : 'ассистента'}`}
  >
    {/* content */}
  </div>
);
```

### 7.2. Клавиатурная навигация

- `Tab` — переход между элементами;
- `Shift+Tab` — назад;
- `Cmd/Ctrl+K` — command palette (будущее);
- `Escape` — закрыть модальные окна;
- `Enter` в форме чата — отправить (если не `Shift+Enter`);
- стрелки вверх/вниз в истории команд.

**Добавить глобальные хоткеи в `apps/web/app/layout.tsx`:**

```typescript
'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';

export function GlobalKeyboardShortcuts() {
  const router = useRouter();

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Cmd/Ctrl+K - command palette (будущее)
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        // open command palette
      }

      // Cmd/Ctrl+N - new chat
      if ((e.metaKey || e.ctrlKey) && e.key === 'n') {
        e.preventDefault();
        router.push('/chat/new');
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [router]);

  return null;
}
```

### 7.3. Focus management

- При открытии диалога фокус должен перейти на первый интерактивный элемент;
- при закрытии — вернуться к триггеру;
- `focus-visible` для показа outline только при клавиатурной навигации.

---

## 8. Тестирование UI

### 8.1. Playwright + axe-core

**Установить:**

```bash
npm install -D @playwright/test @axe-core/playwright
```

**Создать `apps/web/tests/a11y.spec.ts`:**

```typescript
import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

test.describe('Accessibility', () => {
  test('chat page should not have accessibility violations', async ({ page }) => {
    await page.goto('http://localhost:3000/chat');
    
    const accessibilityScanResults = await new AxeBuilder({ page }).analyze();
    
    expect(accessibilityScanResults.violations).toEqual([]);
  });

  test('profile page should not have accessibility violations', async ({ page }) => {
    await page.goto('http://localhost:3000/profile');
    
    const accessibilityScanResults = await new AxeBuilder({ page }).analyze();
    
    expect(accessibilityScanResults.violations).toEqual([]);
  });
});
```

### 8.2. Visual regression

**Playwright screenshot comparison:**

```typescript
test('chat input should match snapshot', async ({ page }) => {
  await page.goto('http://localhost:3000/chat');
  await expect(page.locator('[data-testid="chat-input"]')).toHaveScreenshot();
});
```

---

## 9. Правило: модель без цены

### 9.1. Поведение

**НЕ запрещать** использование модели без настроенной цены.

**Предупреждать:**
- при добавлении модели (inline alert);
- при выборе модели в чате (badge "Без цены" рядом с селектором);
- в отчёте usage (секция "Запросы без оценки стоимости");
- в отчёте бюджета (баннер "Часть запросов не учтена").

### 9.2. Отображение в таблице моделей

**В `apps/web/app/models/page.tsx`:**

```typescript
<TableRow>
  <TableCell>{model.name}</TableCell>
  <TableCell>{model.provider}</TableCell>
  <TableCell>
    {model.hasPrice ? (
      <div className="space-y-1">
        <div className="text-sm">Вход: {model.priceIn} ₽/1M</div>
        <div className="text-sm">Выход: {model.priceOut} ₽/1M</div>
      </div>
    ) : (
      <div className="flex items-center gap-2">
        <Badge variant="outline" className="text-cost-unknown border-cost-unknown">
          Цена не задана
        </Badge>
        <Button size="sm" variant="ghost" onClick={() => handleSetPrice(model.id)}>
          Настроить
        </Button>
      </div>
    )}
  </TableCell>
</TableRow>
```

### 9.3. Отображение в usage report

**Добавить секцию:**

```typescript
{unpricedRequests > 0 && (
  <Alert variant="warning">
    <AlertTriangle className="h-4 w-4" />
    <AlertTitle>Неучтённые запросы</AlertTitle>
    <AlertDescription>
      <p className="mb-2">
        {unpricedRequests} запросов ({unpricedPercentage}%) не учтены в бюджете из-за отсутствия цены модели.
      </p>
      <Button size="sm" variant="outline" onClick={() => router.push('/models')}>
        Настроить цены
      </Button>
    </AlertDescription>
  </Alert>
)}
```

---

## 10. Локализация и i18n (будущее)

**Пока оставить интерфейс на русском**, но подготовить структуру под `next-intl`:

```bash
npm install next-intl
```

**Создать `apps/web/messages/ru.json`:**

```json
{
  "chat": {
    "input_placeholder": "Напишите сообщение...",
    "send": "Отправить",
    "stop": "Остановить",
    "reasoning_depth": "Глубина размышления",
    "local_mode": "Локально",
    "web_access": "Веб-доступ"
  },
  "privacy": {
    "local": "Локально",
    "cloud": "Облако",
    "local_tooltip": "Данные обработаны на вашем компьютере",
    "cloud_tooltip": "Запрос отправлен во внешний AI-провайдер"
  }
}
```

---

## 11. Checklist перед коммитом

Перед каждым коммитом UI-изменений проверить:

- [ ] Все новые компоненты используют shadcn/ui и семантические токены
- [ ] Контраст текста соответствует WCAG AA (минимум 4.5:1)
- [ ] Клавиатурная навигация работает (Tab, Enter, Escape)
- [ ] `aria-label` и `role` атрибуты добавлены где нужно
- [ ] Состояния пустоты (empty states) обработаны
- [ ] Skeleton loading показывается при загрузке
- [ ] Toast/alert для ошибок (не только console.error)
- [ ] Mobile responsive (протестировать на 375px ширине)
- [ ] Dark mode работает корректно
- [ ] TypeScript без ошибок (`npm run typecheck`)
- [ ] Prettier отформатировал код (`npm run format`)
- [ ] Playwright тесты проходят (`npm run test:e2e`)

---

## 12. Фазы реализации (в том же порядке, что и backend)

**Фаза 0:** Дизайн-система (shadcn/ui + токены) — 2 дня  
**Фаза 1:** Онбординг + empty states — 2 дня  
**Фаза 2:** Профиль пользователя — 1 день  
**Фаза 3:** Полный редизайн чата (virtualization, markdown, badges) — 3 дня  
**Фаза 4:** Reasoning depth UI — 0,5 дня  
**Фаза 5:** Локальный режим UI (тумблер + индикатор) — 0,5 дня  
**Фаза 6:** Веб-доступ UI + источники — 1 день  
**Фаза 7:** Accessibility audit + клавиатура — 1 день  
**Фаза 8:** Тесты (Playwright + axe) — 1 день  

**ИТОГО: ~12 дней чистой UI-работы.**

---

## 13. Документация для пользователя

После завершения UI обновить:

**`README.md`** — добавить скриншоты нового интерфейса.

**`docs/USER_GUIDE.md`** — создать пошаговое руководство:
- как настроить провайдера;
- как работает локальный режим;
- как читать индикаторы приватности и стоимости;
- как настроить бюджет;
- как экспортировать данные.

---

## Заключение

Этот файл даёт **полную картину** того, как должен выглядеть интерфейс Personal AI Hub после редизайна. Coding-агент должен:

1. Начать с внедрения дизайн-системы (shadcn/ui + токены);
2. Реализовать компоненты в порядке фаз;
3. Не удалять существующий функционал без явного указания;
4. Проверять доступность и контраст после каждого компонента;
5. Писать Playwright-тесты для критических путей;
6. Документировать каждое изменение в commit message.

**Главное правило:** интерфейс должен подчёркивать уникальность продукта — **контроль расходов + приватность + локальность**. Это не просто красивый чат, это AI-хаб с экономической и информационной дисциплиной.
