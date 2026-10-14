// Проверочная страница дизайн-системы.
// Назначение: изолированная точка проверки, что дизайн-токены и утилиты
// Tailwind v4 действительно скомпилированы (цвета, радиусы, типографика,
// тёмная тема). Используется в E2E-тестах доступности.
// Место в архитектуре: служебная страница UI, не влияет на бизнес-логику.
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export default function DesignSystemPage() {
  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-6 p-8">
      <div>
        <h1 className="text-pah-3xl font-semibold">Дизайн-система</h1>
        <p className="text-muted-foreground mt-2">
          Служебная страница проверки токенов и базовых компонентов.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Кнопки</CardTitle>
          <CardDescription>Варианты и размеры</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          <Button>Основная</Button>
          <Button variant="secondary">Вторичная</Button>
          <Button variant="outline">Контурная</Button>
          <Button variant="ghost">Прозрачная</Button>
          <Button variant="destructive">Опасная</Button>
          <Button size="sm">Малая</Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Статусы и стоимость</CardTitle>
          <CardDescription>Семантические цвета токенов</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          <Badge variant="success">Готово</Badge>
          <Badge variant="warning">Внимание</Badge>
          <Badge variant="destructive">Ошибка</Badge>
          <Badge variant="secondary">Ожидание</Badge>
          <Badge variant="outline" className="text-cost-low border-cost-low">
            Дешёвый запрос
          </Badge>
          <Badge
            variant="outline"
            className="text-cost-medium border-cost-medium"
          >
            Средний запрос
          </Badge>
          <Badge variant="outline" className="text-cost-high border-cost-high">
            Дорогой запрос
          </Badge>
          <Badge
            variant="outline"
            className="text-cost-unknown border-cost-unknown"
          >
            Цена не задана
          </Badge>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Типографика и радиусы</CardTitle>
          <CardDescription>Шкала pah-* и rounded-*</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          <p className="text-pah-2xl">text-pah-2xl</p>
          <p className="text-pah-base">text-pah-base</p>
          <p className="text-pah-xs text-muted-foreground">text-pah-xs</p>
          <div className="flex gap-2">
            <div className="rounded-sm border px-3 py-1 text-pah-xs">sm</div>
            <div className="rounded-md border px-3 py-1 text-pah-xs">md</div>
            <div className="rounded-lg border px-3 py-1 text-pah-xs">lg</div>
            <div className="rounded-xl border px-3 py-1 text-pah-xs">xl</div>
          </div>
        </CardContent>
      </Card>
    </main>
  );
}
