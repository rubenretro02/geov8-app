using System.Globalization;
using System.Windows;
using System.Windows.Media;
using System.Windows.Threading;

namespace GeoV10.UI;

/// <summary>Port of the AnimatedCircle canvas: progress ring while running, thumbs up/down on result.</summary>
public sealed class AnimatedCircle : FrameworkElement
{
    private enum CircleState { Idle, Running, Success, Error }

    private CircleState _state = CircleState.Idle;
    private double _progress, _target;
    private readonly DispatcherTimer _smooth = new() { Interval = TimeSpan.FromMilliseconds(30) };
    private readonly DispatcherTimer _finish = new() { Interval = TimeSpan.FromMilliseconds(20) };
    private bool _finishSuccess;

    private static readonly Brush BgCardHover = MakeBrush("#1a1a25"), Border = MakeBrush("#27272a"),
        Warning = MakeBrush("#f59e0b"), Success = MakeBrush("#10b981"), Error = MakeBrush("#ef4444"),
        SuccessFill = MakeBrush("#0d3d2e"), ErrorFill = MakeBrush("#3d1a1a");

    private static SolidColorBrush MakeBrush(string hex)
    {
        var b = new SolidColorBrush((Color)ColorConverter.ConvertFromString(hex));
        b.Freeze();
        return b;
    }

    public AnimatedCircle()
    {
        Width = 180; Height = 180;
        _smooth.Tick += (_, _) => SmoothStep();
        _finish.Tick += (_, _) => FinishStep();
    }

    public void Start()
    {
        _finish.Stop();
        _state = CircleState.Running; _progress = 0; _target = 0;
        InvalidateVisual();
    }

    public void SetProgress(double percent)
    {
        _target = Math.Min(percent, 100);
        if (_state == CircleState.Running && !_smooth.IsEnabled) _smooth.Start();
    }

    private void SmoothStep()
    {
        if (_state != CircleState.Running) { _smooth.Stop(); return; }
        if (_progress < _target)
        {
            var step = Math.Max(0.5, (_target - _progress) / 10);
            _progress = Math.Min(_progress + step, _target);
            InvalidateVisual();
        }
        else
        {
            _progress = _target;
            _smooth.Stop();
            InvalidateVisual();
        }
    }

    public void Finish(bool success)
    {
        _smooth.Stop();
        _target = 100; _finishSuccess = success;
        _finish.Start();
    }

    private void FinishStep()
    {
        if (_progress < 100)
        {
            _progress = Math.Min(_progress + 3, 100);
            InvalidateVisual();
            return;
        }
        _finish.Stop();
        _state = _finishSuccess ? CircleState.Success : CircleState.Error;
        InvalidateVisual();
    }

    public void Reset()
    {
        _smooth.Stop(); _finish.Stop();
        _state = CircleState.Idle; _progress = 0; _target = 0;
        InvalidateVisual();
    }

    protected override void OnRender(DrawingContext dc)
    {
        var size = Math.Min(ActualWidth, ActualHeight);
        if (size <= 0) return;
        var center = new Point(ActualWidth / 2, ActualHeight / 2);
        var r = size / 2 - 10;

        switch (_state)
        {
            case CircleState.Idle:
                dc.DrawEllipse(BgCardHover, new Pen(Border, 4), center, r, r);
                break;

            case CircleState.Running:
                dc.DrawEllipse(BgCardHover, new Pen(Border, 4), center, r, r);
                var sweep = _progress * 3.6;
                if (sweep > 0) dc.DrawGeometry(null, new Pen(Warning, 4) { StartLineCap = PenLineCap.Round, EndLineCap = PenLineCap.Round }, Arc(center, r, sweep));
                DrawText(dc, $"{(int)_progress}%", center, "Segoe UI", 28, FontWeights.Bold, Warning);
                break;

            case CircleState.Success:
                dc.DrawEllipse(SuccessFill, new Pen(Success, 4), center, r, r);
                DrawText(dc, "👍", center, "Segoe UI Emoji", 48, FontWeights.Normal, Success);
                break;

            case CircleState.Error:
                dc.DrawEllipse(ErrorFill, new Pen(Error, 4), center, r, r);
                DrawText(dc, "👎", center, "Segoe UI Emoji", 48, FontWeights.Normal, Error);
                break;
        }
    }

    private static Geometry Arc(Point c, double r, double sweepDeg)
    {
        if (sweepDeg >= 360) return new EllipseGeometry(c, r, r);
        var start = new Point(c.X, c.Y - r);
        var rad = (sweepDeg - 90) * Math.PI / 180;
        var end = new Point(c.X + r * Math.Cos(rad), c.Y + r * Math.Sin(rad));
        var g = new StreamGeometry();
        using (var ctx = g.Open())
        {
            ctx.BeginFigure(start, false, false);
            ctx.ArcTo(end, new Size(r, r), 0, sweepDeg > 180, SweepDirection.Clockwise, true, false);
        }
        g.Freeze();
        return g;
    }

    private void DrawText(DrawingContext dc, string text, Point center, string font, double size, FontWeight weight, Brush brush)
    {
        var ft = new FormattedText(text, CultureInfo.InvariantCulture, FlowDirection.LeftToRight,
            new Typeface(new FontFamily(font), FontStyles.Normal, weight, FontStretches.Normal),
            size, brush, VisualTreeHelper.GetDpi(this).PixelsPerDip);
        dc.DrawText(ft, new Point(center.X - ft.Width / 2, center.Y - ft.Height / 2));
    }
}
